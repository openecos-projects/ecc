"""Handlers for project-level ``ecc.toml`` declarations."""

import os
import tomllib

from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.project.config_fields import lookup_project_field, parse_project_field_values
from chipcompiler.cli.project.toml_edit import remove_scoped_key, set_scoped_key


def project_set(args, ctx: CommandContext) -> CommandResult:
    field, error = _field_or_error(args.key)
    if error is not None:
        return error
    try:
        value = parse_project_field_values(field, args.values)
    except ValueError as exc:
        return CommandResult.err(
            [error_record("invalid_project_value", key=args.key, reason=str(exc))]
        )
    config_path, missing = _config_path_or_error(ctx)
    if missing is not None:
        return missing
    _set_value(config_path, field, value)
    return CommandResult.ok([_record(field.key, value, "set")])


def project_unset(args, ctx: CommandContext) -> CommandResult:
    field, error = _field_or_error(args.key)
    if error is not None:
        return error
    config_path, missing = _config_path_or_error(ctx)
    if missing is not None:
        return missing
    with open(config_path) as file:
        changed = remove_scoped_key(file.read(), field.table, field.name)
    if changed is None:
        return CommandResult.ok([_record(field.key, None, "no_value")])
    with open(config_path, "w") as file:
        file.write(changed)
    return CommandResult.ok([_record(field.key, None, "unset")])


def project_add(args, ctx: CommandContext) -> CommandResult:
    return _change_rtl(args, ctx, add=True)


def project_remove(args, ctx: CommandContext) -> CommandResult:
    return _change_rtl(args, ctx, add=False)


def project_show(args, ctx: CommandContext) -> CommandResult:
    config_path, missing = _config_path_or_error(ctx)
    if missing is not None:
        return missing
    try:
        with open(config_path, "rb") as file:
            data = tomllib.load(file)
    except tomllib.TOMLDecodeError as exc:
        return CommandResult.err([error_record("invalid_project_config", reason=str(exc))])
    if args.key is not None:
        field, error = _field_or_error(args.key)
        if error is not None:
            return error
        section = data.get(field.table, {})
        value = section.get(field.name) if isinstance(section, dict) else None
        return CommandResult.ok(
            [_record(field.key, value, "set" if value is not None else "no_value")]
        )
    records = []
    for field in _all_fields():
        section = data.get(field.table, {})
        value = section.get(field.name) if isinstance(section, dict) else None
        if value is not None:
            records.append(_record(field.key, value, "set"))
    return CommandResult.ok(records or [{"project": "show", "status": "empty"}])


def _change_rtl(args, ctx: CommandContext, *, add: bool) -> CommandResult:
    if args.key != "design.rtl":
        return CommandResult.err(
            [
                error_record(
                    "unsupported_project_collection",
                    key=args.key,
                    reason="only design.rtl supports add/remove",
                )
            ]
        )
    field = lookup_project_field("design.rtl")
    assert field is not None
    try:
        values = parse_project_field_values(field, args.values)
    except ValueError as exc:
        return CommandResult.err(
            [error_record("invalid_project_value", key=field.key, reason=str(exc))]
        )
    if not isinstance(values, list):
        return CommandResult.err(
            [
                error_record(
                    "invalid_project_value", key=field.key, reason="design.rtl requires a list"
                )
            ]
        )
    config_path, missing = _config_path_or_error(ctx)
    if missing is not None:
        return missing
    try:
        with open(config_path, "rb") as file:
            data = tomllib.load(file)
    except tomllib.TOMLDecodeError as exc:
        return CommandResult.err([error_record("invalid_project_config", reason=str(exc))])
    current = data.get("design", {}).get("rtl", [])
    if not isinstance(current, list) or not all(isinstance(value, str) for value in current):
        return CommandResult.err(
            [error_record("invalid_project_config", reason="design.rtl must be a string list")]
        )
    if add:
        updated = [*current, *(value for value in values if value not in current)]
        status = "added"
    else:
        updated = [value for value in current if value not in values]
        status = "removed"
    _set_value(config_path, field, updated)
    return CommandResult.ok([_record(field.key, updated, status)])


def _set_value(config_path: str, field, value: object) -> None:
    with open(config_path) as file:
        updated = set_scoped_key(file.read(), field.table, field.name, value)
    with open(config_path, "w") as file:
        file.write(updated)


def _field_or_error(key: str):
    field = lookup_project_field(key)
    if field is not None:
        return field, None
    return None, CommandResult.err([error_record("unknown_project_field", key=key)])


def _config_path_or_error(ctx: CommandContext):
    path = os.path.join(ctx.project_dir, "ecc.toml")
    if os.path.isfile(path):
        return path, None
    return None, CommandResult.err([error_record("missing_config", path=path)])


def _record(key: str, value: object, status: str) -> dict:
    return {"project_field": key, "value": value, "status": status, "source": "ecc.toml"}


def _all_fields():
    from chipcompiler.cli.project.config_fields import PROJECT_FIELDS

    return PROJECT_FIELDS
