"""Handlers for the manual macro-placement commands."""

import math
from pathlib import Path

from chipcompiler.cli.command_handlers.param import (
    _find_config_path,
    _load_toml_overrides,
    _manifest_mode_error,
    _remove_param_from_toml,
    _write_param_to_toml,
)
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.project.params import lookup_schema
from chipcompiler.cli.project.workspace_params import (
    set_workspace_param,
    workspace_param_value,
)
from chipcompiler.data.workspace.macro_location import (
    MACRO_ORIENTATIONS,
    parse_macro_location_tcl,
)

MACRO_PARAM = "macro.placements"


def macro_set(args, ctx: CommandContext) -> CommandResult:
    schema = lookup_schema(MACRO_PARAM)
    entry, error = _entry(args)
    if error is not None:
        return error

    if getattr(args, "workspace", None) is not None:
        return _workspace_set(args, ctx, schema, entry)
    return _project_set(args, ctx, schema, entry)


def macro_remove(args, ctx: CommandContext) -> CommandResult:
    schema = lookup_schema(MACRO_PARAM)

    if getattr(args, "workspace", None) is not None:
        return _workspace_remove(args, ctx, schema)
    return _project_remove(args, ctx, schema)


def macro_import(args, ctx: CommandContext) -> CommandResult:
    schema = lookup_schema(MACRO_PARAM)

    try:
        text = Path(args.path).read_text(encoding="utf-8")
    except OSError as exc:
        return CommandResult.err(
            [error_record("file_unreadable", param=MACRO_PARAM, reason=str(exc))],
            exit_code=1,
        )
    try:
        placements = parse_macro_location_tcl(text)
    except ValueError as exc:
        return CommandResult.err(
            [error_record("invalid_value", param=MACRO_PARAM, reason=str(exc))], exit_code=1
        )

    if getattr(args, "workspace", None) is not None:
        return _workspace_import(args, ctx, schema, placements)
    return _project_import(args, ctx, schema, placements)


def macro_show(args, ctx: CommandContext) -> CommandResult:
    schema = lookup_schema(MACRO_PARAM)

    if getattr(args, "workspace", None) is not None:
        from chipcompiler.cli.command_handlers.workspace_params import _load_workspace

        workspace, workspace_error = _load_workspace(ctx)
        if workspace_error is not None:
            return workspace_error
        placements, error = _workspace_placements(workspace, schema)
        if error is not None:
            return error
        from chipcompiler.data.workspace import workspace_config_paths

        file_path = workspace_config_paths(workspace.directory)["macro_location"]
        record = {
            "param": MACRO_PARAM,
            "placements": placements,
            "file": str(file_path),
            "source": "workspace",
            "workspace": ctx.run_id,
        }
        file_placements, file_error = _read_file_placements(file_path)
        if file_error is not None:
            record["file_error"] = file_error
        else:
            record["file_placements"] = file_placements
            record["diverged"] = not _same_placements(placements, file_placements)
        return CommandResult.ok([record])

    manifest_error = _manifest_mode_error(ctx)
    if manifest_error is not None:
        return manifest_error
    placements, load_error = _project_placements(ctx)
    if load_error is not None:
        return load_error
    return CommandResult.ok(
        [
            {
                "param": MACRO_PARAM,
                "placements": placements,
                "source": "ecc.toml",
            }
        ]
    )


# ---------------------------------------------------------------------------
# Workspace scope
# ---------------------------------------------------------------------------


def _workspace_set(args, ctx: CommandContext, schema, entry: dict) -> CommandResult:
    from chipcompiler.cli.command_handlers.workspace_params import _mutate

    written: dict = {}

    def mutation(workspace):
        current, error = _workspace_placements(workspace, schema)
        if error is not None:
            raise ValueError(error.records[0].get("reason", "invalid macro.placements"))
        placements = _upsert(current, entry)
        written["placements"] = placements
        return set_workspace_param(workspace, schema, placements)

    result = _mutate(ctx, schema, mutation, None, "set")
    _annotate(result, args.instance, written.get("placements"))
    return result


def _workspace_remove(args, ctx: CommandContext, schema) -> CommandResult:
    from chipcompiler.cli.command_handlers.workspace_params import _load_workspace, _mutate

    workspace, workspace_error = _load_workspace(ctx)
    if workspace_error is not None:
        return workspace_error
    current, error = _workspace_placements(workspace, schema)
    if error is not None:
        return error
    if not any(entry.get("instance") == args.instance for entry in current):
        return CommandResult.ok(
            [
                {
                    "param": MACRO_PARAM,
                    "instance": args.instance,
                    "placements": current,
                    "status": "absent",
                    "source": "workspace",
                    "workspace": ctx.run_id,
                }
            ]
        )

    remaining = [entry for entry in current if entry.get("instance") != args.instance]
    written: dict = {}

    def mutation(workspace):
        written["placements"] = remaining
        return set_workspace_param(workspace, schema, remaining)

    result = _mutate(ctx, schema, mutation, None, "set")
    record = _annotate(result, args.instance, written.get("placements"))
    if record is not None:
        record["status"] = "removed"
    return result


def _workspace_placements(workspace, schema) -> tuple[list, CommandResult | None]:
    value = workspace_param_value(workspace, schema)
    if not isinstance(value, list):
        return [], CommandResult.err(
            [
                error_record(
                    "invalid_value",
                    param=MACRO_PARAM,
                    reason="macro.placements must be a list of placement objects",
                )
            ],
            exit_code=1,
        )
    return value, None


def _workspace_import(args, ctx, schema, placements: list) -> CommandResult:
    from chipcompiler.cli.command_handlers.workspace_params import _mutate

    def mutation(workspace):
        return set_workspace_param(workspace, schema, placements)

    result = _mutate(ctx, schema, mutation, placements, "set")
    _annotate_import(result, args.path, placements)
    return result


# ---------------------------------------------------------------------------
# Project scope
# ---------------------------------------------------------------------------


def _project_set(args, ctx: CommandContext, schema, entry: dict) -> CommandResult:
    manifest_error = _manifest_mode_error(ctx)
    if manifest_error is not None:
        return manifest_error
    current, load_error = _project_placements(ctx)
    if load_error is not None:
        return load_error

    placements = _upsert(current, entry)
    config_path = _find_config_path(ctx.project_dir)
    if config_path is None:
        return CommandResult.err([error_record("missing_config")], exit_code=1)
    try:
        _write_param_to_toml(config_path, schema, placements)
    except (OSError, ValueError) as exc:
        return CommandResult.err(
            [error_record("config_error", param=MACRO_PARAM, reason=str(exc))], exit_code=1
        )

    return CommandResult.ok(
        [
            {
                "param": MACRO_PARAM,
                "instance": args.instance,
                "x": args.x,
                "y": args.y,
                "orientation": args.orientation,
                "placements": placements,
                "status": "set",
                "source": "ecc.toml",
            }
        ]
    )


def _project_remove(args, ctx: CommandContext, schema) -> CommandResult:
    manifest_error = _manifest_mode_error(ctx)
    if manifest_error is not None:
        return manifest_error
    current, load_error = _project_placements(ctx)
    if load_error is not None:
        return load_error

    if not any(entry.get("instance") == args.instance for entry in current):
        return CommandResult.ok(
            [
                {
                    "param": MACRO_PARAM,
                    "instance": args.instance,
                    "placements": current,
                    "status": "absent",
                    "source": "ecc.toml",
                }
            ]
        )

    remaining = [entry for entry in current if entry.get("instance") != args.instance]
    config_path = _find_config_path(ctx.project_dir)
    if config_path is None:
        return CommandResult.err([error_record("missing_config")], exit_code=1)
    try:
        if remaining:
            _write_param_to_toml(config_path, schema, remaining)
        else:
            _remove_param_from_toml(config_path, schema)
    except (OSError, ValueError) as exc:
        return CommandResult.err(
            [error_record("config_error", param=MACRO_PARAM, reason=str(exc))], exit_code=1
        )

    return CommandResult.ok(
        [
            {
                "param": MACRO_PARAM,
                "instance": args.instance,
                "placements": remaining,
                "status": "removed",
                "source": "ecc.toml",
            }
        ]
    )


def _project_placements(ctx: CommandContext) -> tuple[list, CommandResult | None]:
    overrides, param_errors = _load_toml_overrides(ctx.project_dir)
    if param_errors:
        return [], CommandResult.err(
            [error_record("invalid_param_config", reason=e) for e in param_errors]
        )
    value = overrides.get(MACRO_PARAM, [])
    if not isinstance(value, list):
        return [], CommandResult.err(
            [
                error_record(
                    "invalid_value",
                    param=MACRO_PARAM,
                    reason="macro.placements must be a list of placement objects",
                )
            ],
            exit_code=1,
        )
    return value, None


def _project_import(args, ctx, schema, placements: list) -> CommandResult:
    manifest_error = _manifest_mode_error(ctx)
    if manifest_error is not None:
        return manifest_error
    config_path = _find_config_path(ctx.project_dir)
    if config_path is None:
        return CommandResult.err([error_record("missing_config")], exit_code=1)
    try:
        if placements:
            _write_param_to_toml(config_path, schema, placements)
        else:
            _remove_param_from_toml(config_path, schema)
    except (OSError, ValueError) as exc:
        return CommandResult.err(
            [error_record("config_error", param=MACRO_PARAM, reason=str(exc))], exit_code=1
        )

    return CommandResult.ok(
        [
            {
                "param": MACRO_PARAM,
                "source_file": args.path,
                "placements": placements,
                "status": "imported",
                "source": "ecc.toml",
            }
        ]
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _entry(args) -> tuple[dict, CommandResult | None]:
    if not args.instance.strip():
        return None, CommandResult.err(
            [error_record("invalid_value", param=MACRO_PARAM, reason="instance name is empty")],
            exit_code=1,
        )
    if args.orientation not in MACRO_ORIENTATIONS:
        return None, CommandResult.err(
            [
                error_record(
                    "invalid_value",
                    param=MACRO_PARAM,
                    reason="orientation must be one of " + "/".join(sorted(MACRO_ORIENTATIONS)),
                )
            ],
            exit_code=1,
        )
    if not math.isfinite(args.x) or not math.isfinite(args.y):
        return None, CommandResult.err(
            [error_record("invalid_value", param=MACRO_PARAM, reason="coordinates must be finite")],
            exit_code=1,
        )
    return (
        {
            "instance": args.instance,
            "x": args.x,
            "y": args.y,
            "orientation": args.orientation,
        },
        None,
    )


def _upsert(placements: list, entry: dict) -> list:
    remaining = [item for item in placements if item.get("instance") != entry["instance"]]
    remaining.append(entry)
    return remaining


def _annotate(result: CommandResult, instance: str, placements) -> dict | None:
    """Describe the effective macro state on a workspace mutation result."""
    if not result.records or result.exit_code != 0 or placements is None:
        return None
    record = result.records[0]
    record["instance"] = instance
    record["placements"] = placements
    if record.get("status") != "no_override":
        record["status"] = "set"
    return record


def _annotate_import(result: CommandResult, path: str, placements: list) -> None:
    if not result.records or result.exit_code != 0:
        return
    record = result.records[0]
    record["source_file"] = path
    record["placements"] = placements
    if record.get("status") != "no_override":
        record["status"] = "imported"


def _read_file_placements(path) -> tuple[list | None, str | None]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None, f"{Path(path).name} is missing or unreadable"
    try:
        return parse_macro_location_tcl(text), None
    except ValueError as exc:
        return None, str(exc)


def _same_placements(left: list, right: list) -> bool:
    """Order-insensitive placement comparison; order never affects placement."""
    return sorted(left, key=_placement_sort_key) == sorted(right, key=_placement_sort_key)


def _placement_sort_key(entry: dict) -> tuple:
    return (
        str(entry.get("instance", "")),
        _coordinate_sort_key(entry.get("x")),
        _coordinate_sort_key(entry.get("y")),
        str(entry.get("orientation", "")),
    )


def _coordinate_sort_key(value) -> tuple:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return ("n", float(value))
    return ("s", str(value))
