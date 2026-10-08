"""Workspace-scoped variants of the schema-backed parameter commands."""

from pathlib import Path

from chipcompiler.cli.core.line_records import json_literal
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult, OutputMode
from chipcompiler.cli.project.params import list_schemas, lookup_schema, parse_value, validate_value
from chipcompiler.cli.project.workspace_params import (
    set_workspace_param,
    unset_workspace_param,
    workspace_param_diff,
    workspace_param_step,
    workspace_param_value,
)
from chipcompiler.rtl2gds import normalize_flow_step


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
    selected_step = normalize_flow_step(args.step or "").casefold()
    canonical_step = normalize_flow_step(args.step or "")
    # ``load_workspace`` keeps the flow ledger lazy; use the accessor so
    # persisted steps are hydrated before validating the requested step.
    steps_accessor = getattr(workspace.flow, "steps", None)
    flow_steps = (
        steps_accessor()
        if callable(steps_accessor)
        else workspace.flow.data.get("steps", [])
    )
    flow_step_names = {
        normalize_flow_step(step.get("name", "")).casefold()
        for step in flow_steps
        if isinstance(step, dict) and step.get("name")
    }
    if selected_step and selected_step not in flow_step_names:
        return CommandResult.err([error_record("unknown_step", step=args.step)], exit_code=1)
    first_step = normalize_flow_step(flow_steps[0]["name"]).casefold() if flow_steps else ""
    records = []
    for schema in list_schemas():
        if schema.pdk_target is not None or (not args.all and schema.param not in overrides):
            continue
        schema_steps = {
            normalize_flow_step(schema.group).casefold(),
            normalize_flow_step(schema.applies).casefold(),
        }
        global_at_first_step = schema.applies == "all" and selected_step == first_step
        if selected_step and selected_step not in schema_steps and not global_at_first_step:
            continue
        try:
            value = workspace_param_value(workspace, schema)
        except ValueError:
            continue
        status = "workspace" if schema.param in overrides else "base"
        if ctx.output_mode == OutputMode.PLAIN:
            record = _line_record(ctx, schema, value, status)
            if canonical_step:
                record["step_id"] = canonical_step
            records.append(record)
        else:
            records.append(_record(ctx, schema.param, value, status))
    if ctx.output_mode == OutputMode.PLAIN and not records:
        return CommandResult.ok(
            [
                {
                    "record": "parameter_list",
                    "status": "clean",
                    **({"step_id": canonical_step} if canonical_step else {}),
                    "workspace": ctx.run_id,
                }
            ]
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


def _snapshot_transaction(workspace) -> dict:
    """Capture every declared output file of the mutation sequence.

    The sequence commits three artifacts in turn (params.toml, the derived
    config/*.json files, and the flow ledger); a failure after the first
    commit must roll all of them back or the workspace keeps new parameters
    paired with stale configs and a ledger that lets the next run no-op.
    The declared config set is snapshotted even when a file does not exist
    yet — refresh_workspace_config may create it, and the rollback must
    remove it again. The auto-generated SDC is rewritten by the refresh
    before config validation can fail, so it belongs to the same
    transaction. Values are bytes, or None for not-yet-existing paths.
    """
    from pathlib import Path

    from chipcompiler.data.workspace import workspace_config_paths

    workspace_dir = Path(workspace.directory)
    paths = [
        workspace_dir / "home" / "params.toml",
        workspace_dir / "home" / "flow.json",
        workspace_dir / "home" / "config-derived-manifest.json",
    ]
    paths.extend(
        path for key, path in workspace_config_paths(workspace_dir).items() if key != "dir"
    )
    sdc = getattr(getattr(workspace, "pdk", None), "sdc", None)
    if sdc:
        paths.append(Path(sdc))
    snapshot: dict = {}
    for path in paths:
        if not path.is_file():
            snapshot[path] = None
            continue
        try:
            snapshot[path] = path.read_bytes()
        except OSError as exc:
            # A file that exists but cannot be read must abort the
            # transaction before any mutation: restoring it as absent would
            # delete a real configuration.
            raise OSError(f"cannot snapshot {path}: {exc}") from exc
    return snapshot


def _restore_transaction(snapshot: dict) -> list[str]:
    """Write every snapshotted file back; returns human-readable failures."""
    failures: list[str] = []
    for path, content in snapshot.items():
        try:
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
        except OSError as exc:
            failures.append(f"{path}: {exc}")
    return failures


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
            if (Path(ctx.run_dir) / "home" / "engineering-snapshot.json").is_file():
                return _mutate_via_engine(ctx, workspace, schema, requested_value, status)
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
            try:
                snapshot = _snapshot_transaction(workspace)
            except OSError as exc:
                return CommandResult.err(
                    [
                        error_record(
                            "workspace_param_refresh_failed",
                            param=schema.param,
                            reason=f"cannot snapshot workspace for rollback: {exc}",
                        )
                    ]
                )
            if not save_parameter(workspace.parameters):
                return CommandResult.err(
                    [error_record("workspace_param_save_failed", param=schema.param)]
                )
            try:
                refresh_workspace_config(workspace)
                if schema.param == "macro.placements":
                    from chipcompiler.data.workspace.macro_location import (
                        prune_macro_location_tcl,
                    )

                    prune_macro_location_tcl(workspace)
                flow = EngineFlow(workspace=workspace)
                invalidated = rerun.invalidate_from(flow, step)
            except Exception as exc:
                rollback_failures = _restore_transaction(snapshot)
                reason = str(exc)
                if rollback_failures:
                    reason += "; rollback incomplete: " + "; ".join(rollback_failures)
                return CommandResult.err(
                    [
                        error_record(
                            "workspace_param_refresh_failed", param=schema.param, reason=reason
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


def _mutate_via_engine(ctx, workspace, schema, requested_value: object, status: str):
    from chipcompiler.data.workspace_parameters import workspace_param_diff, workspace_param_step
    from chipcompiler.engine import update_workspace_step_configuration
    from chipcompiler.engine.snapshot import read_engineering_snapshot
    from chipcompiler.engine.workspace_lifecycle import WorkspaceLifecycleError

    overrides = workspace_param_diff(workspace)
    existing = next((item for item in overrides if item["key"] == schema.param), None)
    if status == "unset" and existing is None:
        return CommandResult.ok([_record(ctx, schema.param, None, "no_override")])
    value = requested_value if status == "set" else existing["baseline"]
    step = workspace_param_step(schema)
    try:
        revision = read_engineering_snapshot(workspace)["workspaceRevision"]
        updated = update_workspace_step_configuration(
            ctx.run_dir,
            revision,
            step,
            {schema.param: value},
            command_id="",
        )
    except WorkspaceLifecycleError as exc:
        return CommandResult.err(
            [error_record(exc.code, param=schema.param, reason=str(exc), **exc.details)]
        )
    except Exception as exc:
        return CommandResult.err(
            [error_record("workspace_param_refresh_failed", param=schema.param, reason=str(exc))]
        )

    updated_steps = updated.flow.steps()
    target = normalize_flow_step(step).casefold()
    start = next(
        (
            index
            for index, item in enumerate(updated_steps)
            if normalize_flow_step(item.get("name", "")).casefold() == target
        ),
        len(updated_steps),
    )
    invalidated = [
        str(item.get("name", ""))
        for item in updated_steps[start:]
        if item.get("name") and item.get("state") == "Unstart"
    ]
    record = _record(ctx, schema.param, value, status)
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


def _line_record(ctx: CommandContext, schema, value: object, status: str) -> dict:
    """Return the stable machine record used by GUI workspace parameter reads."""
    record: dict[str, object] = {
        "record": "parameter",
        "id": schema.param,
        "type": schema.type,
        "value_literal": json_literal(value),
        "default_literal": json_literal(schema.default),
        "applies_to": schema.applies,
        "status": status,
        "source": status,
        "workspace": ctx.run_id,
    }
    if schema.range is not None:
        record["range_literal"] = json_literal(list(schema.range))
    if schema.choices is not None:
        record["choices_literal"] = json_literal(list(schema.choices))
    if schema.unit is not None:
        record["unit"] = schema.unit
    if schema.description:
        record["description"] = schema.description
    return record
