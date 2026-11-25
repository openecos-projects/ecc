"""Handlers for project-level ``ecc.toml`` declarations."""

import json
import os
import tomllib

from chipcompiler.cli.core.errors import CommandError, command_handler
from chipcompiler.cli.core.records import error_record, warning_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.project.config_fields import lookup_project_field, parse_project_field_values
from chipcompiler.cli.project.toml_edit import remove_scoped_key, set_scoped_key
from chipcompiler.project.config_write import edit_project_config
from chipcompiler.project.manifest import CONFIG_FILENAME


@command_handler
def project_set(args, ctx: CommandContext) -> CommandResult:
    field = _require_field(args.key)
    try:
        value = parse_project_field_values(field, args.values)
    except ValueError as exc:
        return CommandResult.err(
            [error_record("invalid_project_value", key=args.key, reason=str(exc))]
        )
    config_path = _require_config_path(ctx)
    if ctx.project_state == "manifest":
        raw = json.dumps(value) if field.list_value else str(value)
        error = _apply_manifest_change(ctx, sets=(f"{field.key}={raw}",))
    else:
        _set_value(config_path, field, value)
        error = None
    if error is not None:
        raise CommandError.from_result(error)
    return CommandResult.ok(
        [*_shadowed_clock_warnings(config_path, (field.key,)), _record(field.key, value, "set")]
    )


def project_apply(args, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.project.project_application import ProjectApplicationError, apply_project

    try:
        changed = apply_project(
            ctx.project_dir,
            sets=args.sets,
            unsets=args.unsets,
            add_rtl=args.add_rtl,
            remove_rtl=args.remove_rtl,
            blocking=not args.no_wait,
        )
    except BlockingIOError:
        return CommandResult.err([error_record("project_busy")], exit_code=20)
    except ProjectApplicationError as exc:
        return CommandResult.err([error_record(exc.code, key=exc.key, reason=str(exc))])
    set_keys = tuple(item.partition("=")[0].strip() for item in args.sets or ())
    config_path = os.path.join(ctx.project_dir, CONFIG_FILENAME)
    return CommandResult.ok(
        [
            *_shadowed_clock_warnings(config_path, set_keys),
            {"project": "apply", "status": "applied", "changed": changed},
        ]
    )


_CLOCK_KEYS = ("design.clock_port", "design.frequency_mhz")


def _shadowed_clock_warnings(config_path: str, keys: tuple[str, ...]) -> list[dict]:
    """Warn when the external primary-clock declaration overrides a design key."""
    shadowed = [key for key in _CLOCK_KEYS if key in keys]
    if not shadowed:
        return []
    from chipcompiler.cli.project.config import load_project_config

    try:
        cfg = load_project_config(config_path)
    except (OSError, ValueError):
        return []
    if not cfg.design_sdc or cfg._timing_input_error is not None:
        return []
    return [
        warning_record(
            "timing_inputs_override_design",
            keys=shadowed,
            reason="design.sdc supplies the primary clock target "
            "and frequency, and [design] clock_port/frequency_mhz are not used",
            timing_input=cfg.design_sdc,
        )
    ]


def project_baseline(args, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.project.project_application import (
        ProjectApplicationError,
        select_qor_baseline,
    )
    from chipcompiler.project.manifest import ManifestError

    try:
        select_qor_baseline(ctx.project_dir, args.workspace_id, args.reason)
    except (ProjectApplicationError, ManifestError) as exc:
        return CommandResult.err([error_record("project_baseline_failed", reason=str(exc))])
    return CommandResult.ok(
        [{"project": "baseline", "status": "selected", "workspace": args.workspace_id}]
    )


def project_reconcile(args, ctx: CommandContext) -> CommandResult:
    from chipcompiler.cli.project.project_application import (
        ProjectApplicationError,
        reconcile_project_state,
    )
    from chipcompiler.project.manifest import ManifestError

    try:
        report = reconcile_project_state(ctx.project_dir, blocking=not args.no_wait)
    except BlockingIOError:
        return CommandResult.err([error_record("workspace_busy")], exit_code=20)
    except (ProjectApplicationError, ManifestError, OSError) as exc:
        return CommandResult.err([error_record("project_reconcile_failed", reason=str(exc))])
    record = {
        "project": "reconcile",
        "status": "repaired" if report.repairs else "consistent",
        "repairs": list(report.repairs),
        "busy": list(report.busy),
        "errors": list(report.errors),
    }
    if report.errors:
        return CommandResult.err([record])
    if report.busy:
        return CommandResult.err([record], exit_code=20)
    return CommandResult.ok([record])


@command_handler
def project_unset(args, ctx: CommandContext) -> CommandResult:
    field = _require_field(args.key)
    config_path = _require_config_path(ctx)
    try:

        def unset(text: str) -> str | None:
            return remove_scoped_key(text, field.table, field.name)

        if ctx.project_state == "manifest":
            with open(config_path) as file:
                changed = unset(file.read()) is not None
            error = _apply_manifest_change(ctx, unsets=(field.key,))
            if error is not None:
                return error
        else:
            changed = edit_project_config(config_path, unset)
    except (OSError, UnicodeDecodeError) as exc:
        return CommandResult.err([_io_error(config_path, exc)])
    return CommandResult.ok([_record(field.key, None, "unset" if changed else "no_value")])


@command_handler
def project_add(args, ctx: CommandContext) -> CommandResult:
    return _change_rtl(args, ctx, add=True)


@command_handler
def project_remove(args, ctx: CommandContext) -> CommandResult:
    return _change_rtl(args, ctx, add=False)


@command_handler
def project_show(args, ctx: CommandContext) -> CommandResult:
    config_path = _require_config_path(ctx)
    try:
        with open(config_path, "rb") as file:
            data = tomllib.load(file)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        return CommandResult.err([_io_error(config_path, exc)])
    if args.key is not None:
        field = _require_field(args.key)
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
    config_path = _require_config_path(ctx)
    if ctx.project_state == "manifest":
        error = _apply_manifest_change(
            ctx,
            add_rtl=tuple(values) if add else (),
            remove_rtl=() if add else tuple(values),
        )
        if error is not None:
            raise CommandError.from_result(error)
        with open(config_path, "rb") as file:
            updated = tomllib.load(file)["design"]["rtl"]
    else:
        updated = []

        def edit(text: str) -> str:
            nonlocal updated
            current = tomllib.loads(text).get("design", {}).get("rtl", [])
            if not isinstance(current, list) or not all(
                isinstance(value, str) for value in current
            ):
                raise CommandError(
                    [
                        error_record(
                            "invalid_project_config", reason="design.rtl must be a string list"
                        )
                    ]
                )
            if add:
                updated = [*current, *(value for value in values if value not in current)]
            else:
                updated = [value for value in current if value not in values]
            return set_scoped_key(text, field.table, field.name, updated)

        try:
            edit_project_config(config_path, edit)
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            return CommandResult.err([_io_error(config_path, exc)])
    return CommandResult.ok([_record(field.key, updated, "added" if add else "removed")])


def _apply_manifest_change(
    ctx: CommandContext,
    *,
    sets: tuple[str, ...] = (),
    unsets: tuple[str, ...] = (),
    add_rtl: tuple[str, ...] = (),
    remove_rtl: tuple[str, ...] = (),
) -> CommandResult | None:
    """Apply one project edit to ``ecc.toml`` and ``project.json`` atomically.

    Skip full project validation to preserve project-set behavior on partially
    configured projects; the field value was already validated above.
    """
    from chipcompiler.cli.project.project_application import (
        ProjectApplicationError,
        apply_project,
    )
    from chipcompiler.project.manifest import ManifestError

    try:
        apply_project(
            ctx.project_dir,
            sets=sets,
            unsets=unsets,
            add_rtl=add_rtl,
            remove_rtl=remove_rtl,
            validate=False,
        )
    except BlockingIOError:
        return CommandResult.err([error_record("project_busy")], exit_code=20)
    except (ManifestError, ProjectApplicationError) as exc:
        code = getattr(exc, "code", "manifest_invalid")
        fields = {"reason": str(exc)}
        key = getattr(exc, "key", None)
        if key:
            fields["key"] = key
        return CommandResult.err([error_record(code, **fields)])
    return None


def _set_value(config_path: str, field, value: object) -> None:
    """Apply one field edit, raising CommandError when the edit fails."""
    try:
        edit_project_config(
            config_path, lambda text: set_scoped_key(text, field.table, field.name, value)
        )
    except (OSError, UnicodeDecodeError) as exc:
        raise CommandError([_io_error(config_path, exc)]) from exc


def _io_error(config_path: str, exc: Exception) -> dict:
    return error_record("config_error", path=config_path, reason=str(exc))


def _require_field(key: str):
    field = lookup_project_field(key)
    if field is None:
        raise CommandError([error_record("unknown_project_field", key=key)])
    return field


def _require_config_path(ctx: CommandContext) -> str:
    path = os.path.join(ctx.project_dir, CONFIG_FILENAME)
    if not os.path.isfile(path):
        raise CommandError([error_record("missing_config", path=path)])
    return path


def _record(key: str, value: object, status: str) -> dict:
    return {"project_field": key, "value": value, "status": status, "source": "ecc.toml"}


def _all_fields():
    from chipcompiler.cli.project.config_fields import PROJECT_FIELDS

    return PROJECT_FIELDS
