from __future__ import annotations

import os
import re

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
    toml_overrides = _load_toml_overrides(ctx.project_dir)
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

    toml_overrides = _load_toml_overrides(ctx.project_dir)
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
    toml_overrides = _load_toml_overrides(ctx.project_dir)
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
    import sys
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
    import sys
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
    import sys
    target = file or sys.stdout
    r = records[0]

    print(f"  {r['param']}", file=target)
    for field in ("value", "default", "source", "type", "applies",
                  "maps_to", "description", "range", "choices", "unit"):
        val = r.get(field)
        if val is not None:
            label = field.replace("_", " ")
            print(f"    {label:14s} {val}", file=target)


def render_param_set_text(records, file=None):
    import sys
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
    import sys
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


def _load_toml_overrides(project_dir: str) -> dict[str, object]:
    config_path = _find_config_path(project_dir)
    if config_path is None:
        return {}

    from chipcompiler.cli.config import load_project_config
    cfg = load_project_config(config_path)
    return cfg.params_overrides


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


def _apply_scoped_param_edit(text: str, group: str, name: str, value: object) -> str:
    value_str = _format_toml_value(value)

    section_header = f"[params.{group}]"
    header_idx = text.find(section_header)
    if header_idx == -1:
        header_idx = text.find("[params]")
        if header_idx == -1:
            return text.rstrip() + f"\n\n[params.{group}]\n{name} = {value_str}\n"
        after_header = text.find("\n", header_idx)
        insert = f"\n\n[params.{group}]\n{name} = {value_str}"
        if after_header == -1:
            return text + insert + "\n"
        next_sec = re.search(r"^\[", text[after_header:], re.MULTILINE)
        if next_sec:
            pos = after_header + next_sec.start()
            return text[:pos] + insert + "\n" + text[pos:]
        return text + insert + "\n"

    after_header = text.find("\n", header_idx + len(section_header))
    if after_header == -1:
        return text + f"\n{name} = {value_str}\n"
    after_header += 1

    next_sec = re.search(r"^\[", text[after_header:], re.MULTILINE)
    section_end = after_header + next_sec.start() if next_sec else len(text)

    section_body = text[after_header:section_end]
    key_pattern = re.compile(rf"^{re.escape(name)}\s*=[^\n]*$", re.MULTILINE)
    key_match = key_pattern.search(section_body)

    if key_match:
        new_line = f"{name} = {value_str}"
        new_body = section_body[:key_match.start()] + new_line + section_body[key_match.end():]
        return text[:after_header] + new_body + text[section_end:]
    else:
        insert = f"{name} = {value_str}\n"
        return text[:after_header] + insert + text[after_header:]


def _remove_scoped_param_key(text: str, group: str, name: str) -> str | None:
    section_header = f"[params.{group}]"
    header_idx = text.find(section_header)
    if header_idx == -1:
        return None

    after_header = text.find("\n", header_idx + len(section_header))
    if after_header == -1:
        return None
    after_header += 1

    next_sec = re.search(r"^\[", text[after_header:], re.MULTILINE)
    section_end = after_header + next_sec.start() if next_sec else len(text)

    section_body = text[after_header:section_end]
    key_pattern = re.compile(rf"^{re.escape(name)}\s*=[^\n]*\n?", re.MULTILINE)
    key_match = key_pattern.search(section_body)
    if not key_match:
        return None

    new_body = section_body[:key_match.start()] + section_body[key_match.end():]
    remaining_keys = [l for l in new_body.strip().split("\n") if l.strip()]
    if not remaining_keys:
        result = text[:header_idx].rstrip("\n") + "\n" + text[section_end:].lstrip("\n")
        return result if result.strip() else None
    else:
        return text[:after_header] + new_body + text[section_end:]


def _format_toml_value(val: object) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        return str(val)
    if isinstance(val, str):
        escaped = val.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(val, (list, tuple)):
        items = ", ".join(_format_toml_value(v) for v in val)
        return f"[{items}]"
    return str(val)
