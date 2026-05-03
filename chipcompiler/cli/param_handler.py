from __future__ import annotations

import os
import tomllib

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
from chipcompiler.cli.types import CommandContext, CommandResult


def param_list(args, ctx: CommandContext) -> CommandResult:
    schemas = list_schemas()
    records = []
    for s in schemas:
        records.append(_schema_to_record(s))
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
        if rp.source != "default":
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
# Internal helpers
# ---------------------------------------------------------------------------

def _schema_to_record(schema):
    record = {
        "param": schema.param,
        "group": schema.group,
        "type": schema.type,
        "default": schema.default,
        "applies": schema.applies,
        "description": schema.description,
    }
    if schema.range is not None:
        record["range"] = f"[{schema.range[0]}, {schema.range[1]}]"
    if schema.choices is not None:
        record["choices"] = ", ".join(schema.choices)
    if schema.unit is not None:
        record["unit"] = schema.unit
    return record


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

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    params = data.get("params", {})
    if not isinstance(params, dict):
        params = {}

    group_table = params.get(group, {})
    if not isinstance(group_table, dict):
        group_table = {}
    group_table[name] = value
    params[group] = group_table
    data["params"] = params

    _write_toml_data(config_path, data)


def _remove_param_from_toml(config_path: str, key: str) -> bool:
    group, _, name = key.partition(".")

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    params = data.get("params")
    if not isinstance(params, dict):
        return False

    group_table = params.get(group)
    if not isinstance(group_table, dict):
        return False

    if name not in group_table:
        return False

    del group_table[name]
    if not group_table:
        del params[group]
    if not params:
        del data["params"]

    _write_toml_data(config_path, data)
    return True


def _write_toml_data(path: str, data: dict) -> None:
    lines = []
    _serialize_toml(data, lines, [])
    with open(path, "w") as f:
        f.write("\n".join(lines))
        if lines:
            f.write("\n")


def _serialize_toml(data: dict, lines: list[str], path: list[str]) -> None:
    scalars: list[tuple[str, object]] = []
    tables: list[tuple[str, dict]] = []
    arrays: list[tuple[str, list]] = []

    for key in _toml_sort_keys(data):
        val = data[key]
        if isinstance(val, dict):
            tables.append((key, val))
        elif isinstance(val, list):
            arrays.append((key, val))
        else:
            scalars.append((key, val))

    for key, val in scalars:
        lines.append(f"{key} = {_toml_value(val)}")

    for key, val in arrays:
        items = ", ".join(_toml_value(v) for v in val)
        lines.append(f"{key} = [{items}]")

    for key, val in tables:
        lines.append("")
        header_path = path + [key]
        lines.append(f"[{'.'.join(header_path)}]")
        _serialize_toml(val, lines, header_path)


def _toml_sort_keys(data: dict) -> list[str]:
    def sort_key(k):
        v = data[k]
        if isinstance(v, dict):
            return (1, k)
        if isinstance(v, list):
            return (1, k)
        return (0, k)
    return sorted(data.keys(), key=sort_key)


def _toml_value(val: object) -> str:
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
        items = ", ".join(_toml_value(v) for v in val)
        return f"[{items}]"
    return str(val)
