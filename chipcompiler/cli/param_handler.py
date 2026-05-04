from __future__ import annotations

import os
import re
import sys

from chipcompiler.cli.output import disclosure_cmd
from chipcompiler.cli.params import (
    ResolvedParam,
    build_backend_overrides,
    is_known_key,
    list_groups,
    list_schemas,
    lookup_schema,
    parse_cli_overrides,
    parse_value,
    resolve_parameters,
    validate_value,
)
from chipcompiler.cli.records import error_record
from chipcompiler.cli.types import CommandContext, CommandResult, OutputMode


def param_list(args, ctx: CommandContext) -> CommandResult:
    toml_overrides, param_errors = _load_toml_overrides(ctx.project_dir)
    if param_errors:
        return CommandResult.err([error_record("invalid_param_config", reason=e) for e in param_errors])
    resolved, _ = resolve_parameters(toml_overrides=toml_overrides)
    project = ctx.project

    records = []
    for rp in resolved:
        s = rp.schema
        record = {
            "param": s.param,
            "group": s.group,
            "name": s.name,
            "value": rp.value,
            "default": s.default,
            "source": rp.source,
            "type": s.type,
            "applies": s.applies,
            "maps_to": _maps_to_str(s.maps_to),
            "description": s.description,
            "inspect": disclosure_cmd(f"ecc param show {s.param}", project),
        }
        if s.range is not None:
            record["range"] = f"[{s.range[0]}, {s.range[1]}]"
        if s.choices is not None:
            record["choices"] = ", ".join(s.choices)
        if s.unit is not None:
            record["unit"] = s.unit
        records.append(record)

    return CommandResult.ok(records)


def param_show(args, ctx: CommandContext) -> CommandResult:
    key = args.key
    schema = lookup_schema(key)
    if schema is None:
        return CommandResult.err([error_record(
            "unknown_parameter",
            param=key,
        )], exit_code=1)

    toml_overrides, param_errors = _load_toml_overrides(ctx.project_dir)
    if param_errors:
        return CommandResult.err([error_record("invalid_param_config", reason=e) for e in param_errors])
    resolved, _ = resolve_parameters(toml_overrides=toml_overrides)
    rp = next(r for r in resolved if r.param == key)

    record = {
        "param": rp.param,
        "value": rp.value,
        "default": rp.default,
        "source": rp.source,
        "type": schema.type,
        "applies": schema.applies,
        "maps_to": _maps_to_str(schema.maps_to),
        "description": schema.description,
        "inspect": disclosure_cmd(f"ecc param show {rp.param}", ctx.project),
        "set": disclosure_cmd(f"ecc param set {rp.param}", ctx.project),
        "run": disclosure_cmd(f"ecc run --set {rp.param}=<value>", ctx.project),
    }
    if schema.range is not None:
        record["range"] = f"[{schema.range[0]}, {schema.range[1]}]"
    if schema.choices is not None:
        record["choices"] = ", ".join(schema.choices)
    if schema.unit is not None:
        record["unit"] = schema.unit

    return CommandResult.ok([record])


def param_set(args, ctx: CommandContext) -> CommandResult:
    key = args.key
    raw_value = args.value

    schema = lookup_schema(key)
    if schema is None:
        return CommandResult.err([error_record(
            "unknown_parameter",
            param=key,
        )], exit_code=1)

    try:
        value = parse_value(raw_value, schema)
    except ValueError as exc:
        return CommandResult.err([error_record(
            "invalid_value",
            param=key,
            reason=str(exc),
        )], exit_code=1)

    val_errors = validate_value(value, schema)
    if val_errors:
        return CommandResult.err([error_record(
            "invalid_value",
            param=key,
            reason=val_errors[0],
        )], exit_code=1)

    config_path = _find_config_path(ctx.project_dir)
    if config_path is None:
        return CommandResult.err([error_record(
            "missing_config",
        )], exit_code=1)

    _write_param_to_toml(config_path, key, value)

    return CommandResult.ok([{
        "param": key,
        "value": value,
        "status": "set",
        "source": "ecc.toml",
    }])


def param_unset(args, ctx: CommandContext) -> CommandResult:
    key = args.key

    schema = lookup_schema(key)
    if schema is None:
        return CommandResult.err([error_record(
            "unknown_parameter",
            param=key,
        )], exit_code=1)

    config_path = _find_config_path(ctx.project_dir)
    if config_path is None:
        return CommandResult.ok([{
            "param": key,
            "status": "no_override",
            "source": "default",
        }])

    removed = _remove_param_from_toml(config_path, key)

    if removed:
        return CommandResult.ok([{
            "param": key,
            "status": "unset",
            "value": schema.default,
            "source": "default",
        }])
    return CommandResult.ok([{
        "param": key,
        "status": "no_override",
        "source": "default",
    }])


def param_diff(args, ctx: CommandContext) -> CommandResult:
    toml_overrides, param_errors = _load_toml_overrides(ctx.project_dir)
    if param_errors:
        return CommandResult.err([error_record("invalid_param_config", reason=e) for e in param_errors])
    resolved, _ = resolve_parameters(toml_overrides=toml_overrides)

    records = []
    for rp in resolved:
        if rp.value != rp.default:
            records.append({
                "param": rp.param,
                "value": rp.value,
                "default": rp.default,
                "source": rp.source,
            })

    if not records:
        return CommandResult.ok([{"diff_status": "clean"}])

    return CommandResult.ok(records)


# ---------------------------------------------------------------------------
# Pretty rendering for param commands
# ---------------------------------------------------------------------------

def render_param_result(result, mode: OutputMode, file=None) -> bool:
    """Render param-specific output. Returns True if handled, False otherwise."""
    target = file or sys.stdout

    if mode == OutputMode.JSON:
        from chipcompiler.cli.render import render_json
        render_json(result, file=target)
        return True
    if mode == OutputMode.JSONL:
        from chipcompiler.cli.render import render_jsonl
        render_jsonl(result, file=target)
        return True
    if mode == OutputMode.PLAIN:
        from chipcompiler.cli.render import render_plain
        render_plain(result.records, file=target)
        return True

    return False


def render_param_list_text(records, file=None):
    target = file or sys.stdout
    groups: dict[str, list] = {}
    for r in records:
        g = r.get("group", "")
        groups.setdefault(g, []).append(r)

    for group_name, group_records in groups.items():
        print(f"  {group_name}", file=target)
        for r in group_records:
            val = r.get("value")
            src = r.get("source", "default")
            line = f"    {r['param']:30s} {val}"
            if src != "default":
                line += f"  ({src})"
            print(line, file=target)


def render_param_show_text(records, file=None):
    target = file or sys.stdout
    r = records[0]

    print(f"  {r['param']}", file=target)
    for field in ("value", "default", "source", "type", "applies",
                  "maps_to", "description", "range", "choices", "unit",
                  "inspect", "set", "run"):
        val = r.get(field)
        if val is not None:
            label = field.replace("_", " ")
            print(f"    {label:14s} {val}", file=target)


def render_param_set_text(records, file=None):
    target = file or sys.stdout
    r = records[0]
    status = r.get("status", "")
    if status == "set":
        print(f"  set {r['param']} = {r['value']} (ecc.toml)", file=target)
    elif status == "no_override":
        print(f"  {r['param']}: no override to remove", file=target)
    elif status == "unset":
        print(f"  unset {r['param']} (now default: {r['value']})", file=target)
    else:
        from chipcompiler.cli.render import render_text
        render_text(records, file=target)


def render_param_diff_text(records, file=None):
    target = file or sys.stdout
    if len(records) == 1 and records[0].get("diff_status") == "clean":
        print("  No overrides.", file=target)
        return
    for r in records:
        print(f"  {r['param']:30s} {r['value']} (was {r['default']}, {r['source']})", file=target)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _maps_to_str(maps_to):
    if isinstance(maps_to, str):
        return maps_to
    parts = [f"{k}.{v}" for k, v in maps_to.items()]
    return ", ".join(parts)


def _find_config_path(project_dir: str) -> str | None:
    path = os.path.join(project_dir, "ecc.toml")
    return path if os.path.isfile(path) else None


def _load_toml_overrides(project_dir: str) -> tuple[dict[str, object], list[str]]:
    from chipcompiler.cli.config import load_project_config

    config_path = _find_config_path(project_dir)
    if config_path is None:
        return {}, []

    cfg = load_project_config(config_path)
    errors = list(getattr(cfg, "_param_errors", []))
    toml_error = getattr(cfg, "_toml_error", None)
    if toml_error:
        errors.insert(0, f"malformed ecc.toml: {toml_error}")
    overrides = dict(cfg.params_overrides)
    if "design.frequency_mhz" not in overrides and cfg.design_frequency_mhz > 0:
        overrides["design.frequency_mhz"] = cfg.design_frequency_mhz
    return overrides, errors


def _write_param_to_toml(config_path: str, key: str, value: object) -> None:
    group, _, name = key.partition(".")

    with open(config_path, "r") as f:
        original = f.read()

    new_text = _apply_scoped_param_edit(original, group, name, value)

    with open(config_path, "w") as f:
        f.write(new_text)


def _remove_param_from_toml(config_path: str, key: str) -> bool:
    group, _, name = key.partition(".")

    with open(config_path, "r") as f:
        original = f.read()

    result = _remove_scoped_param_key(original, group, name)
    if result is None:
        return False

    with open(config_path, "w") as f:
        f.write(result)
    return True


_TABLE_HEADER_RE = re.compile(r"^[ \t]*\[([^\]]+)\][ \t]*(?:#.*)?$", re.MULTILINE)


def _find_table_span(text: str, table_name: str) -> tuple[int, int] | None:
    """Return (body_start, body_end) for a TOML table, or None."""
    for m in _TABLE_HEADER_RE.finditer(text):
        if m.group(1).strip() == table_name:
            header_end = m.end()
            nl = text.find("\n", header_end)
            if nl == -1:
                body_start = len(text)
            else:
                body_start = nl + 1
            next_header = _TABLE_HEADER_RE.search(text, body_start)
            body_end = next_header.start() if next_header else len(text)
            return body_start, body_end
    return None


def _extend_multiline_value(text: str, match_end: int) -> int:
    """Extend match end past continuation lines for multiline TOML values.

    After matching `key = ...` on one line, consume subsequent lines if the
    value has unclosed brackets (arrays or inline tables).
    """
    line_start = text.rfind("\n", 0, match_end) + 1
    matched_line = text[line_start:match_end]

    depth = 0
    eq_pos = matched_line.find("=")
    if eq_pos >= 0:
        for ch in matched_line[eq_pos + 1:]:
            if ch in ("[", "{"):
                depth += 1
            elif ch in ("]", "}"):
                depth -= 1

    if depth <= 0:
        return match_end

    pos = match_end
    while pos < len(text) and depth > 0:
        ch = text[pos]
        if ch in ("[", "{"):
            depth += 1
        elif ch in ("]", "}"):
            depth -= 1
        pos += 1

    while pos < len(text) and text[pos] in (" ", "\t"):
        pos += 1
    if pos < len(text) and text[pos] == "\n":
        pos += 1

    return pos


def _apply_scoped_param_edit(text: str, group: str, name: str, value: object) -> str:
    value_str = _format_toml_value(value)
    target_table = f"params.{group}"

    span = _find_table_span(text, target_table)
    if span is None:
        params_span = _find_table_span(text, "params")
        if params_span is None:
            return text.rstrip() + f"\n\n[{target_table}]\n{name} = {value_str}\n"
        body_start, body_end = params_span
        insert = f"\n\n[{target_table}]\n{name} = {value_str}"
        next_header = _TABLE_HEADER_RE.search(text, body_start)
        if next_header:
            pos = next_header.start()
            return text[:pos] + insert + "\n" + text[pos:]
        return text + insert + "\n"

    body_start, body_end = span
    section_body = text[body_start:body_end]
    key_pattern = re.compile(rf"^(\s*){re.escape(name)}\s*=[^\n]*$", re.MULTILINE)
    key_match = key_pattern.search(section_body)

    if key_match:
        indent = key_match.group(1)
        end = _extend_multiline_value(section_body, key_match.end())
        new_line = f"{indent}{name} = {value_str}"
        new_body = section_body[:key_match.start()] + new_line + section_body[end:]
        return text[:body_start] + new_body + text[body_end:]
    else:
        insert = f"{name} = {value_str}\n"
        return text[:body_start] + insert + text[body_start:]


def _remove_scoped_param_key(text: str, group: str, name: str) -> str | None:
    target_table = f"params.{group}"

    span = _find_table_span(text, target_table)
    if span is None:
        return None

    body_start, body_end = span
    section_body = text[body_start:body_end]
    key_pattern = re.compile(rf"^\s*{re.escape(name)}\s*=[^\n]*\n?", re.MULTILINE)
    key_match = key_pattern.search(section_body)
    if not key_match:
        return None

    end = _extend_multiline_value(section_body, key_match.end())
    # Consume trailing newline after multiline value
    if section_body[end:end + 1] == "\n":
        end += 1
    new_body = section_body[:key_match.start()] + section_body[end:]
    remaining_keys = [l for l in new_body.strip().split("\n") if l.strip()]
    if not remaining_keys:
        header_match = None
        for m in _TABLE_HEADER_RE.finditer(text):
            if m.group(1).strip() == target_table:
                header_match = m
                break
        if header_match is None:
            return None
        header_start = header_match.start()
        result = text[:header_start].rstrip("\n") + "\n" + text[body_end:].lstrip("\n")
        return result if result.strip() else None
    else:
        return text[:body_start] + new_body + text[body_end:]


def _format_toml_value(val: object) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        escaped = val.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(val, (list, tuple)):
        items = ", ".join(_format_toml_value(v) for v in val)
        return f"[{items}]"
    return str(val)
