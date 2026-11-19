"""Workspace-scoped variants of the schema-backed parameter commands."""

from pathlib import Path

from chipcompiler.cli.core.errors import CommandError, command_handler
from chipcompiler.cli.core.line_records import json_literal
from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult, OutputMode
from chipcompiler.data.step_parameters import (
    ParameterStepError,
    is_step_scoped,
    parse_step_key,
    step_key,
    step_values,
)
from chipcompiler.params import (
    list_schemas,
    parse_value,
    set_workspace_param,
    unset_workspace_param,
    validate_value,
    workspace_param_diff,
    workspace_param_step,
    workspace_param_value,
)


@command_handler
def param_set(args, ctx: CommandContext) -> CommandResult:
    schema, step = _schema_and_workspace_error(args.key, ctx)
    try:
        value = parse_value(args.value, schema)
    except ValueError as exc:
        return CommandResult.err([error_record("invalid_value", param=args.key, reason=str(exc))])
    pdk = str(_load_workspace(ctx).parameters.data.get("pdk") or "") or None
    errors = validate_value(value, schema, pdk)
    if errors:
        return CommandResult.err([error_record("invalid_value", param=args.key, reason=errors[0])])
    return _mutate(
        ctx,
        schema,
        lambda workspace: set_workspace_param(workspace, schema, value, step),
        value,
        "set",
        step,
    )


@command_handler
def param_unset(args, ctx: CommandContext) -> CommandResult:
    schema, step = _schema_and_workspace_error(args.key, ctx)

    def unset(workspace):
        return unset_workspace_param(workspace, schema, step)

    return _mutate(ctx, schema, unset, None, "unset", step)


@command_handler
def param_show(args, ctx: CommandContext) -> CommandResult:
    schema, step = _schema_and_workspace_error(args.key, ctx)
    workspace = _load_workspace(ctx)
    try:
        value = workspace_param_value(workspace, schema, step=step)
    except ValueError as exc:
        return CommandResult.err(
            [error_record("workspace_param_refresh_required", param=args.key, reason=str(exc))]
        )
    return CommandResult.ok([_record(ctx, _key(schema, step), value, "workspace")])


@command_handler
def param_list(args, ctx: CommandContext) -> CommandResult:
    workspace = _load_workspace(ctx)
    selected_step = str(args.step or "")
    canonical_step = str(args.step or "")
    overrides = {
        record["key"]
        for record in workspace_param_diff(workspace)
        if record.get("step") in (None, canonical_step or None)
    }
    # ``load_workspace`` keeps the flow ledger lazy; use the accessor so
    # persisted steps are hydrated before validating the requested step.
    steps_accessor = getattr(workspace.flow, "steps", None)
    raw_steps = (
        steps_accessor() if callable(steps_accessor) else workspace.flow.data.get("steps", [])
    )
    flow_steps = (
        [step for step in raw_steps if isinstance(step, dict)]
        if isinstance(raw_steps, list)
        else []
    )
    flow_step_names = {
        str(step.get("name", ""))
        for step in flow_steps
        if isinstance(step, dict) and step.get("name")
    }
    if selected_step and selected_step not in flow_step_names:
        return CommandResult.err([error_record("unknown_step", step=args.step)], exit_code=1)
    first_step = str(flow_steps[0]["name"]) if flow_steps else ""
    pdk = str(workspace.parameters.data.get("pdk") or "") or None
    records = []
    for schema in list_schemas():
        if schema.pdk_target is not None:
            continue
        if not selected_step and is_step_scoped(schema):
            # Without a step, a step-scoped parameter lists its step values.
            for step in _listed_steps(workspace, schema, show_all=bool(args.all)):
                records.append(_list_row(ctx, workspace, schema, step, pdk, qualified=True))
            continue
        if not args.all and schema.param not in overrides:
            continue
        if selected_step and not schema.listed_at(selected_step, first_step):
            continue
        try:
            records.append(
                _list_row(
                    ctx,
                    workspace,
                    schema,
                    canonical_step or None,
                    pdk,
                    status="workspace" if schema.param in overrides else "base",
                )
            )
        except ValueError:
            continue
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


@command_handler
def param_diff(args, ctx: CommandContext) -> CommandResult:
    workspace = _load_workspace(ctx)
    records = [
        {
            "param": record["key"]
            if record.get("step") is None
            else step_key(record["step"], record["key"]),
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
    ctx: CommandContext,
    schema,
    mutation,
    requested_value: object,
    status: str,
    scope: str | None = None,
) -> CommandResult:
    from chipcompiler.data import refresh_workspace_config, save_parameter
    from chipcompiler.engine import EngineFlow, rerun
    from chipcompiler.utility.workspace_lock import workspace_lock

    # Reject a workspace that was not selected before taking its lock:
    # workspace_lock would create <name>.lock for an undeclared name.
    _workspace_scope_error(ctx)
    try:
        with workspace_lock(Path(ctx.run_dir)):
            workspace = _load_workspace(ctx)
            if (Path(ctx.run_dir) / "home" / "engineering-snapshot.json").is_file():
                return _mutate_via_engine(
                    ctx, workspace, schema, mutation, requested_value, status, scope
                )
            try:
                result = mutation(workspace)
            except ParameterStepError as exc:
                return CommandResult.err(
                    [error_record(exc.code, param=_key(schema, scope), reason=str(exc))]
                )
            except ValueError as exc:
                return CommandResult.err(
                    [
                        error_record(
                            "workspace_param_refresh_required", param=schema.param, reason=str(exc)
                        )
                    ]
                )
            if result is None:
                return CommandResult.ok([_record(ctx, _key(schema, scope), None, "no_override")])
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
                from chipcompiler.data.flow.options import (
                    sync_flow_options_projection,
                )

                sync_flow_options_projection(workspace, persist=True)
                if schema.param == "macro.placements":
                    from chipcompiler.data.workspace.macro_location import (
                        prune_macro_location_tcl,
                    )

                    prune_macro_location_tcl(workspace)
                if step is None:
                    invalidated = []
                else:
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
    record = _record(ctx, _key(schema, scope), effective_value, status)
    if step is not None:
        record["from_step"] = step
    record["invalidated_steps"] = invalidated
    return CommandResult.ok([record])


def _mutate_via_engine(
    ctx, workspace, schema, mutation, requested_value: object, status: str, scope: str | None
):
    from chipcompiler.engine.snapshot import read_engineering_snapshot
    from chipcompiler.engine.workspace.configuration import apply_workspace_parameters
    from chipcompiler.engine.workspace.lifecycle import WorkspaceLifecycleError
    from chipcompiler.params import workspace_param_diff, workspace_param_step

    key = _key(schema, scope)
    overrides = workspace_param_diff(workspace)
    existing = next(
        (item for item in overrides if item["key"] == schema.param and item.get("step") == scope),
        None,
    )
    if status == "unset" and existing is None:
        return CommandResult.ok([_record(ctx, key, None, "no_override")])
    if status == "set":
        if requested_value is None:
            mutation(workspace)
            value = workspace_param_value(workspace, schema)
        else:
            value = requested_value
    else:
        if existing is None:
            return CommandResult.ok([_record(ctx, key, None, "no_override")])
        value = existing["baseline"]
    step = workspace_param_step(schema, workspace, scope)
    try:
        revision = read_engineering_snapshot(workspace)["workspaceRevision"]
        # The engine validates the (step-qualified) key and invalidates from
        # the earliest step the change feeds.
        updated = apply_workspace_parameters(
            ctx.run_dir,
            revision,
            {key: value} if status == "set" else {},
            (key,) if status == "unset" else (),
            command_id="",
        )
    except WorkspaceLifecycleError as exc:
        return CommandResult.err(
            [error_record(exc.code, param=key, reason=str(exc), **exc.details)]
        )
    except Exception as exc:
        return CommandResult.err(
            [error_record("workspace_param_refresh_failed", param=key, reason=str(exc))]
        )

    invalidated = []
    if step is not None:
        updated_steps = updated.flow.steps()
        target = str(step)
        start = next(
            (
                index
                for index, item in enumerate(updated_steps)
                if str(item.get("name", "")) == target
            ),
            len(updated_steps),
        )
        invalidated = [
            str(item.get("name", ""))
            for item in updated_steps[start:]
            if item.get("name") and item.get("state") == "Unstart"
        ]
    record = _record(ctx, key, value, status)
    if step is not None:
        record["from_step"] = step
    record["invalidated_steps"] = invalidated
    return CommandResult.ok([record])


def _listed_steps(workspace, schema, *, show_all: bool) -> list[str]:
    """Steps whose value of step-scoped *schema* an unscoped ``param list`` shows.

    Edited (journaled) step values always; with ``--all`` also every stored one.
    """
    steps = [
        record["step"]
        for record in workspace_param_diff(workspace)
        if record["key"] == schema.param and record.get("step") is not None
    ]
    if show_all:
        steps.extend(
            step
            for step, values in step_values(workspace.parameters.data).items()
            if schema.param in values
        )
    return list(dict.fromkeys(steps))


def _list_row(
    ctx: CommandContext,
    workspace,
    schema,
    step: str | None,
    pdk: str | None,
    *,
    status: str | None = None,
    qualified: bool = False,
) -> dict:
    """One ``param list`` row of *schema* at *step*; *qualified* keys it ``<step>:<param>``."""
    value = workspace_param_value(workspace, schema, step=step)
    if status is None:
        edited = any(
            record["key"] == schema.param and record.get("step") == step
            for record in workspace_param_diff(workspace)
        )
        status = "workspace" if edited else "base"
    if ctx.output_mode != OutputMode.PLAIN:
        return _record(ctx, _key(schema, step if qualified else None), value, status)
    record = _line_record(ctx, schema, value, status, pdk)
    if step is not None:
        record["step_id"] = step
    return record


def _key(schema, step: str | None) -> str:
    return schema.param if step is None else step_key(step, schema.param)


def _schema_and_workspace_error(key: str, ctx: CommandContext):
    """The schema and step of a (possibly ``<step>:``-qualified) parameter *key*.

    A step-scoped (DreamPlace) parameter must name its step, to be read or changed.
    """
    step, schema, key_error = parse_step_key(key)
    if schema is None:
        raise CommandError([error_record("unknown_parameter", param=key)])
    if key_error is not None:
        code = "parameter_step_required" if step is None else "parameter_not_applicable"
        raise CommandError([error_record(code, param=key, reason=key_error)])
    if not schema.output_only:
        try:
            workspace_param_step(schema)
        except ValueError as exc:
            raise CommandError(
                [error_record("workspace_param_refresh_required", param=key, reason=str(exc))]
            ) from exc
    _workspace_scope_error(ctx)
    return schema, step


def _load_workspace(ctx: CommandContext):
    _workspace_scope_error(ctx)
    from chipcompiler.data import load_workspace

    try:
        workspace = load_workspace(ctx.run_dir)
    except Exception as exc:
        raise CommandError(
            [error_record("invalid_workspace", workspace=ctx.run_dir, reason=str(exc))]
        ) from exc
    if workspace is None:
        raise CommandError([error_record("invalid_workspace", workspace=ctx.run_dir)])
    return workspace


def _workspace_scope_error(ctx: CommandContext) -> None:
    if ctx.manifest_error:
        raise CommandError(
            [error_record(ctx.manifest_error.split(":", 1)[0], reason=ctx.manifest_error)]
        )
    if ctx.project_state != "manifest" or ctx.run_id is None:
        raise CommandError(
            [
                error_record(
                    "workspace_param_requires_managed_workspace",
                    reason="--workspace must select a workspace declared in project.json",
                )
            ]
        )


def _record(ctx: CommandContext, key: str, value: object, status: str) -> dict:
    return {
        "param": key,
        "value": value,
        "status": status,
        "source": "workspace",
        "workspace": ctx.run_id,
    }


def _line_record(
    ctx: CommandContext, schema, value: object, status: str, pdk: str | None = None
) -> dict:
    """Return the stable machine record used by GUI workspace parameter reads."""
    record: dict[str, object] = {
        "record": "parameter",
        "id": schema.param,
        "type": schema.type,
        "value_literal": json_literal(value),
        "default_literal": json_literal(schema.default_for(pdk)),
        "applies_to": schema.applies,
        "status": status,
        "source": status,
        "workspace": ctx.run_id,
    }
    if schema.range is not None:
        record["range_literal"] = json_literal(list(schema.range))
    choices = schema.choices_for(pdk)
    if choices is not None:
        record["choices_literal"] = json_literal(list(choices))
    if schema.unit is not None:
        record["unit"] = schema.unit
    if schema.description:
        record["description"] = schema.description
    return record
