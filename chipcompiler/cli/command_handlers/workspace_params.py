"""Workspace-scoped variants of the schema-backed parameter commands."""

from pathlib import Path

from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.cli.project.params import list_schemas, lookup_schema, parse_value, validate_value
from chipcompiler.cli.project.workspace_params import (
    set_workspace_param,
    unset_workspace_param,
    workspace_param_diff,
    workspace_param_step,
    workspace_param_value,
)


def param_set(args, ctx: CommandContext) -> CommandResult:
    schema, error = _schema_and_workspace_error(args.key, ctx)
    if error is not None:
        return error
    try:
        value = parse_value(args.value, schema)
    except ValueError as exc:
        return CommandResult.err([error_record("invalid_value", param=args.key, reason=str(exc))])
    errors = validate_value(value, schema)
    if errors:
        return CommandResult.err([error_record("invalid_value", param=args.key, reason=errors[0])])
    return _mutate(
        ctx, schema, lambda workspace: set_workspace_param(workspace, schema, value), value, "set"
    )


def param_unset(args, ctx: CommandContext) -> CommandResult:
    schema, error = _schema_and_workspace_error(args.key, ctx)
    if error is not None:
        return error

    def unset(workspace):
        return unset_workspace_param(workspace, schema)

    return _mutate(ctx, schema, unset, None, "unset")


def param_show(args, ctx: CommandContext) -> CommandResult:
    schema, error = _schema_and_workspace_error(args.key, ctx)
    if error is not None:
        return error
    workspace, workspace_error = _load_workspace(ctx)
    if workspace_error is not None:
        return workspace_error
    try:
        value = workspace_param_value(workspace, schema)
    except ValueError as exc:
        return CommandResult.err(
            [error_record("workspace_param_refresh_required", param=args.key, reason=str(exc))]
        )
    return CommandResult.ok([_record(ctx, schema.param, value, "workspace")])


def param_list(args, ctx: CommandContext) -> CommandResult:
    workspace, workspace_error = _load_workspace(ctx)
    if workspace_error is not None:
        return workspace_error
    overrides = {record["key"] for record in workspace_param_diff(workspace)}
    selected_step = (args.step or "").casefold()
    records = []
    for schema in list_schemas():
        if schema.pdk_target is not None or (not args.all and schema.param not in overrides):
            continue
        if selected_step and selected_step not in {
            schema.group.casefold(),
            schema.applies.casefold(),
        }:
            continue
        try:
            value = workspace_param_value(workspace, schema)
        except ValueError:
            continue
        records.append(
            _record(ctx, schema.param, value, "workspace" if schema.param in overrides else "base")
        )
    return CommandResult.ok(
        records or [{"param": "list", "status": "clean", "workspace": ctx.run_id}]
    )


def param_diff(args, ctx: CommandContext) -> CommandResult:
    workspace, workspace_error = _load_workspace(ctx)
    if workspace_error is not None:
        return workspace_error
    records = [
        {
            "param": record["key"],
            "value": record.get("value"),
            "baseline": record["baseline"],
            "source": "workspace",
            "workspace": ctx.run_id,
        }
        for record in workspace_param_diff(workspace)
    ]
    return CommandResult.ok(records or [{"diff_status": "clean", "workspace": ctx.run_id}])


def _mutate(
    ctx: CommandContext, schema, mutation, requested_value: object, status: str
) -> CommandResult:
    from chipcompiler.data import refresh_workspace_config, save_parameter
    from chipcompiler.engine import EngineFlow, rerun
    from chipcompiler.engine.reconcile import _workspace_lock

    try:
        with _workspace_lock(Path(ctx.run_dir)):
            workspace, workspace_error = _load_workspace(ctx)
            if workspace_error is not None:
                return workspace_error
            try:
                result = mutation(workspace)
            except ValueError as exc:
                return CommandResult.err(
                    [
                        error_record(
                            "workspace_param_refresh_required", param=schema.param, reason=str(exc)
                        )
                    ]
                )
            if result is None:
                return CommandResult.ok([_record(ctx, schema.param, None, "no_override")])
            value, step = result
            if not save_parameter(workspace.parameters):
                return CommandResult.err(
                    [error_record("workspace_param_save_failed", param=schema.param)]
                )
            try:
                refresh_workspace_config(workspace)
                flow = EngineFlow(workspace=workspace)
                invalidated = rerun.invalidate_from(flow, step)
            except Exception as exc:
                return CommandResult.err(
                    [
                        error_record(
                            "workspace_param_refresh_failed", param=schema.param, reason=str(exc)
                        )
                    ]
                )
    except OSError as exc:
        return CommandResult.err(
            [error_record("workspace_param_lock_failed", param=schema.param, reason=str(exc))]
        )
    effective_value = requested_value if status == "set" else value
    record = _record(ctx, schema.param, effective_value, status)
    record["from_step"] = step
    record["invalidated_steps"] = invalidated
    return CommandResult.ok([record])


def _schema_and_workspace_error(key: str, ctx: CommandContext):
    schema = lookup_schema(key)
    if schema is None:
        return None, CommandResult.err([error_record("unknown_parameter", param=key)])
    try:
        workspace_param_step(schema)
    except ValueError as exc:
        return None, CommandResult.err(
            [error_record("workspace_param_refresh_required", param=key, reason=str(exc))]
        )
    scope_error = _workspace_scope_error(ctx)
    if scope_error is not None:
        return None, scope_error
    return schema, None


def _load_workspace(ctx: CommandContext):
    scope_error = _workspace_scope_error(ctx)
    if scope_error is not None:
        return None, scope_error
    from chipcompiler.data import load_workspace

    try:
        workspace = load_workspace(ctx.run_dir)
    except Exception as exc:
        return None, CommandResult.err(
            [error_record("invalid_workspace", workspace=ctx.run_dir, reason=str(exc))]
        )
    if workspace is None:
        return None, CommandResult.err([error_record("invalid_workspace", workspace=ctx.run_dir)])
    return workspace, None


def _workspace_scope_error(ctx: CommandContext) -> CommandResult | None:
    if ctx.manifest_error:
        return CommandResult.err(
            [error_record(ctx.manifest_error.split(":", 1)[0], reason=ctx.manifest_error)]
        )
    if ctx.project_state != "manifest" or ctx.run_id is None:
        return CommandResult.err(
            [
                error_record(
                    "workspace_param_requires_managed_workspace",
                    reason="--workspace must select a workspace declared in project.json",
                )
            ]
        )
    return None


def _record(ctx: CommandContext, key: str, value: object, status: str) -> dict:
    return {
        "param": key,
        "value": value,
        "status": status,
        "source": "workspace",
        "workspace": ctx.run_id,
    }
