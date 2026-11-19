from copy import deepcopy
from pathlib import Path
from typing import Any

from chipcompiler.data import StateEnum, load_workspace, save_parameter
from chipcompiler.data.step_parameters import (
    ParameterStepError,
    check_parameter_step,
    is_step_scoped,
    split_step_key,
    step_key,
)
from chipcompiler.data.workspace import workspace_config_paths
from chipcompiler.data.workspace.transaction import WorkspaceFileTransaction
from chipcompiler.engine.flow import EngineFlow
from chipcompiler.engine.rerun import invalidate_after, invalidate_from
from chipcompiler.engine.snapshot.store import (
    SNAPSHOT_FILENAME,
    STALE_SNAPSHOT_FILENAME,
    EngineeringSnapshotError,
    ensure_engineering_snapshot,
    invalidate_engineering_snapshot,
    open_workspace_snapshot,
    refresh_engineering_snapshot,
)
from chipcompiler.params import (
    display_key_for,
    knob_id_for,
    list_schemas,
    lookup_schema,
    unset_workspace_param,
    update_workspace_param_value,
    validate_schema_type,
    validate_value,
    workspace_param_step,
    workspace_param_value,
)
from chipcompiler.rtl2gds import get_flow_builders
from chipcompiler.utility import JsonReadError

from ..macro_location_handoff import (
    prune_macro_location_after_write as _prune_macro_location_after_write,
)
from ..macro_location_handoff import (
    verify_published_macro_location as _verify_published_macro_location,
)
from ..parameter_steps import earliest_flow_step, edit_scope, require_flow_step, step_catalog
from .lifecycle import (
    WorkspaceLifecycleError,
    _load_committed_workspace,
    command_retry_matches,
    workspace_command_fingerprint,
    write_workspace_command,
)


def update_workspace_configuration(
    target_directory: str | Path,
    expected_workspace_revision: int,
    configuration: object,
    workspace_bindings: object,
    command_id: str = "",
):
    target = Path(target_directory).expanduser().resolve()
    if not target.is_dir():
        raise WorkspaceLifecycleError("workspace_missing", f"Workspace not found: {target}")
    return _run_file_transaction(
        target,
        lambda: _update_workspace_configuration(
            target,
            expected_workspace_revision,
            configuration,
            workspace_bindings,
            command_id,
        ),
    )


def apply_workspace_parameters(
    target_directory: str | Path,
    expected_workspace_revision: int,
    sets: dict[str, object],
    unsets: tuple[str, ...],
    *,
    step_id: str | None = None,
    commit_step_output: bool = False,
    command_id: str = "",
):
    """Atomically apply and verify a validated batch of Workspace parameters."""
    target = Path(target_directory).expanduser().resolve()
    if not target.is_dir():
        raise WorkspaceLifecycleError("workspace_missing", f"Workspace not found: {target}")
    return _run_file_transaction(
        target,
        lambda: _apply_workspace_parameters(
            target,
            expected_workspace_revision,
            sets,
            unsets,
            step_id=step_id,
            commit_step_output=commit_step_output,
            command_id=command_id,
        ),
    )


def _apply_workspace_parameters(
    target: Path,
    expected_workspace_revision: int,
    sets: dict[str, object],
    unsets: tuple[str, ...],
    *,
    step_id: str | None,
    commit_step_output: bool,
    command_id: str,
):
    set_keys = set(sets)
    unset_keys = set(unsets)
    if not set_keys and not unset_keys:
        raise WorkspaceLifecycleError("parameter_patch_empty", "At least one change is required")
    if len(unset_keys) != len(unsets) or set_keys & unset_keys:
        raise WorkspaceLifecycleError(
            "conflicting_parameter_patch", "Parameters cannot be repeated or set and unset"
        )
    fingerprint = workspace_command_fingerprint(
        "parameter_apply",
        {
            "sets": sets,
            "unsets": sorted(unset_keys),
            "stepId": step_id,
            "commitStepOutput": commit_step_output,
        },
        {},
        expected_workspace_revision,
    )
    if command_id and command_retry_matches(target, command_id, fingerprint):
        return _load_committed_workspace(target)

    workspace = _load_committed_workspace(target)
    snapshot = ensure_engineering_snapshot(workspace)
    if snapshot["workspaceRevision"] != expected_workspace_revision:
        raise WorkspaceLifecycleError(
            "revision_conflict",
            "Workspace Revision does not match",
            {
                "expectedWorkspaceRevision": expected_workspace_revision,
                "actualWorkspaceRevision": snapshot["workspaceRevision"],
            },
        )

    allowed: set[str] | None = None
    step: str | None = None
    if step_id is not None:
        step, step_schemas = step_catalog(workspace, step_id)
        allowed = {schema.param for schema in step_schemas}

    schemas = {}
    scopes: dict[str, str | None] = {}
    identities: set[tuple[str | None, str]] = set()
    normalized_sets = {}
    affected_steps = []
    for parameter in (*sets, *unsets):
        # A key may name its step (``placement:place.target_density``).
        key_step, name = split_step_key(parameter)
        schema = lookup_schema(name)
        if schema is None or schema.pdk_target is not None:
            raise WorkspaceLifecycleError("unknown_parameter", f"Unknown parameter: {parameter}")
        scope = edit_scope(schema, parameter, key_step, step, allowed, identities)
        try:
            check_parameter_step(schema, scope if is_step_scoped(schema) else key_step)
            affected_step = workspace_param_step(schema, workspace, scope)
        except ParameterStepError as exc:
            raise WorkspaceLifecycleError(exc.code, str(exc)) from exc
        except ValueError as exc:
            raise WorkspaceLifecycleError("parameter_requires_refresh", str(exc)) from exc
        if affected_step is not None:
            require_flow_step(workspace, parameter, affected_step, step_value=scope is not None)
            affected_steps.append(affected_step)
        schemas[parameter] = schema
        scopes[parameter] = scope
    for parameter, value in sets.items():
        schema = schemas[parameter]
        normalized, type_error = validate_schema_type(value, schema)
        errors = [type_error] if type_error else _value_errors(workspace, normalized, schema)
        if parameter == "macro.placements" and isinstance(normalized, list):
            from chipcompiler.data.workspace.macro_location import validate_placements

            errors.extend(validate_placements(normalized))
        if errors:
            raise WorkspaceLifecycleError("invalid_parameter", str(errors[0]))
        normalized_sets[parameter] = normalized

    first_step = earliest_flow_step(workspace, affected_steps) if affected_steps else None
    if commit_step_output:
        if step is None or first_step is None:
            raise WorkspaceLifecycleError(
                "step_output_commit_requires_step",
                "commit_step_output requires parameters scoped to a Flow Step",
            )
        if str(step) != str(first_step):
            raise WorkspaceLifecycleError(
                "step_output_scope_mismatch",
                "Published step output must belong to the earliest affected Flow Step",
                {"step": step, "firstAffectedStep": first_step},
            )
        selected = next(
            (item for item in workspace.flow.steps() if item.get("name") == first_step),
            None,
        )
        if selected is None or selected.get("state") != StateEnum.Success.value:
            raise WorkspaceLifecycleError(
                "step_output_not_published",
                f"Flow Step output is not committed successfully: {first_step}",
                {"step": first_step, "state": selected.get("state") if selected else None},
            )

    changed = False
    for parameter, value in normalized_sets.items():
        schema, scope = schemas[parameter], scopes[parameter]
        if workspace_param_value(workspace, schema, step=scope) != value:
            update_workspace_param_value(workspace, schema, value, step=scope)
            changed = True
    for parameter in unsets:
        if unset_workspace_param(workspace, schemas[parameter], scopes[parameter]) is not None:
            changed = True

    if not changed:
        if commit_step_output and "macro.placements" in (set_keys | unset_keys):
            _verify_published_macro_location(workspace)
        write_workspace_command(
            target,
            command_id,
            fingerprint,
            snapshot["workspaceId"],
            snapshot["workspaceRevision"],
        )
        return workspace
    if not save_parameter(workspace.parameters):
        raise OSError("Failed to save Workspace parameters")
    from chipcompiler.data import refresh_workspace_config
    from chipcompiler.data.flow.options import sync_flow_options_projection

    refresh_workspace_config(workspace)
    sync_flow_options_projection(workspace, persist=True)
    _prune_macro_location_after_write(workspace, set_keys)
    if commit_step_output and "macro.placements" in (set_keys | unset_keys):
        _verify_published_macro_location(workspace)
    if first_step is None:
        updated = refresh_engineering_snapshot(
            workspace,
            workspace_id=snapshot["workspaceId"],
            cause="workspace.output_parameters_applied",
        )
        write_workspace_command(
            target,
            command_id,
            fingerprint,
            updated["workspaceId"],
            updated["workspaceRevision"],
        )
        return _load_committed_workspace(target)
    if commit_step_output:
        invalidated = invalidate_after(EngineFlow(workspace), first_step)
        if invalidated:
            updated = invalidate_engineering_snapshot(
                workspace,
                workspace_id=snapshot["workspaceId"],
                cause="workspace.published_step_parameters_applied",
                first_invalidated_step=invalidated[0],
            )
        else:
            updated = refresh_engineering_snapshot(
                workspace,
                workspace_id=snapshot["workspaceId"],
                cause="workspace.published_step_parameters_applied",
            )
    else:
        invalidate_from(EngineFlow(workspace), first_step)
        updated = invalidate_engineering_snapshot(
            workspace,
            workspace_id=snapshot["workspaceId"],
            cause="workspace.parameters_applied",
            first_invalidated_step=first_step,
        )
    write_workspace_command(
        target,
        command_id,
        fingerprint,
        updated["workspaceId"],
        updated["workspaceRevision"],
    )
    return _load_committed_workspace(target)


def _value_errors(workspace: Any, value: object, schema: Any) -> list[str]:
    """Range and choice errors of *value* under the Workspace's PDK family."""
    return validate_value(value, schema, workspace.pdk.name)


def _update_workspace_configuration(
    target: Path,
    expected_workspace_revision: int,
    configuration: object,
    workspace_bindings: object,
    command_id: str,
):
    if not isinstance(configuration, dict) or not isinstance(workspace_bindings, dict):
        raise WorkspaceLifecycleError(
            "workspace_spec_invalid", "Workspace configuration and bindings must be objects"
        )
    config = {str(key): value for key, value in configuration.items()}
    unknown_sections = config.keys() - {"design", "pdk", "parameters"}
    if unknown_sections:
        raise WorkspaceLifecycleError(
            "workspace_spec_invalid", f"Unknown configuration section: {min(unknown_sections)}"
        )
    if config.get("design") or config.get("pdk"):
        raise WorkspaceLifecycleError(
            "workspace_structure_change_requires_update",
            "Design and PDK changes require a structural Workspace Update",
        )
    requested = config.get("parameters", {})
    if not isinstance(requested, dict):
        raise WorkspaceLifecycleError("workspace_spec_invalid", "parameters must be an object")
    parameters = {str(key): value for key, value in requested.items()}
    fingerprint = workspace_command_fingerprint(
        "configuration", config, workspace_bindings, expected_workspace_revision
    )
    if command_id and command_retry_matches(target, command_id, fingerprint):
        return _load_committed_workspace(target)

    workspace = _load_committed_workspace(target)
    current = ensure_engineering_snapshot(workspace)
    if current["workspaceRevision"] != expected_workspace_revision:
        raise WorkspaceLifecycleError(
            "revision_conflict",
            "Workspace Revision does not match",
            {
                "expectedWorkspaceRevision": expected_workspace_revision,
                "actualWorkspaceRevision": current["workspaceRevision"],
            },
        )

    changed = False
    changed_schemas = []
    for parameter, value in parameters.items():
        schema = lookup_schema(parameter)
        if schema is None or schema.pdk_target is not None:
            raise WorkspaceLifecycleError("unknown_parameter", f"Unknown parameter: {parameter}")
        normalized, type_error = validate_schema_type(value, schema)
        errors = [type_error] if type_error else _value_errors(workspace, normalized, schema)
        if errors:
            raise WorkspaceLifecycleError("invalid_parameter", str(errors[0]))
        if is_step_scoped(schema):
            raise WorkspaceLifecycleError(
                "parameter_step_required",
                f"{parameter} is set per step; update it through its step configuration",
            )
        if workspace_param_value(workspace, schema) != normalized:
            update_workspace_param_value(workspace, schema, normalized)
            changed = True
            changed_schemas.append(schema)

    if not changed:
        write_workspace_command(
            target,
            command_id,
            fingerprint,
            current["workspaceId"],
            current["workspaceRevision"],
        )
        return workspace
    if not save_parameter(workspace.parameters):
        raise OSError("Failed to save Workspace parameters")
    from chipcompiler.data import refresh_workspace_config
    from chipcompiler.data.flow.options import sync_flow_options_projection

    refresh_workspace_config(workspace)
    sync_flow_options_projection(workspace, persist=True)
    _prune_macro_location_after_write(workspace, set(parameters))
    if changed_schemas and all(schema.output_only for schema in changed_schemas):
        updated = refresh_engineering_snapshot(
            workspace,
            workspace_id=current["workspaceId"],
            cause="workspace.output_configuration_updated",
        )
        write_workspace_command(
            target,
            command_id,
            fingerprint,
            updated["workspaceId"],
            updated["workspaceRevision"],
        )
        return _load_committed_workspace(target)
    flow = EngineFlow(workspace)
    steps = workspace.flow.steps()
    if steps:
        invalidate_from(flow, str(steps[0]["name"]))
    updated = invalidate_engineering_snapshot(
        workspace,
        workspace_id=current["workspaceId"],
        cause="workspace.configuration_updated",
    )
    write_workspace_command(
        target,
        command_id,
        fingerprint,
        updated["workspaceId"],
        updated["workspaceRevision"],
    )
    return _load_committed_workspace(target)


def read_workspace_configuration(workspace: Any, *, strict: bool = False) -> dict[str, Any]:
    projection = build_workspace_configuration_projection(workspace, strict=strict)
    snapshot = _read_snapshot_metadata(workspace)
    return {**snapshot, **projection}


def build_workspace_configuration_projection(
    workspace: Any, *, strict: bool = False
) -> dict[str, Any]:
    """Build configuration fields without reading Snapshot metadata.

    A step-scoped (DreamPlace) parameter is also projected at each declared
    step in the flow under ``<step>:<param>``, with that step's value.
    """
    steps = workspace.flow.steps()
    flow_names = [str(step.get("name", "")) for step in steps if step.get("name")]
    parameters = {}
    for schema in list_schemas():
        if schema.pdk_target is not None:
            continue
        scopes = [None]
        if is_step_scoped(schema):
            scopes += [step for step in schema.steps if step in flow_names]
        for scope in scopes:
            key = schema.param if scope is None else step_key(scope, schema.param)
            try:
                parameters[key] = workspace_param_value(
                    workspace, schema, step=scope, strict=strict
                )
            except (OSError, ValueError, JsonReadError):
                if strict:
                    raise
    flow = {"flowId": _flow_id(flow_names)}
    if flow_names:
        flow.update({"fromStepId": flow_names[0], "throughStepId": flow_names[-1]})
    inputs, input_bindings = _workspace_inputs(workspace)
    pdk_mode = "manual" if workspace.parameters.data.get("pdk_config") else "default"
    pdk_files, pdk_file_bindings = (
        _workspace_pdk_files(workspace) if pdk_mode == "manual" else ([], {})
    )
    return {
        "workspaceSpec": {
            "schemaVersion": 1,
            "design": {
                "name": workspace.design.name,
                "topModule": workspace.design.top_module,
                "clockPort": str(workspace.parameters.data.get("clock", "")),
            },
            "inputMode": workspace.parameters.data.get("_input_mode")
            if workspace.parameters.data.get("_input_mode") in {"rtl", "postSynthesis", "def"}
            else ("postSynthesis" if workspace.design.origin_def is not None else "rtl"),
            "inputs": inputs,
            "pdk": {
                "familyId": workspace.pdk.name,
                "version": workspace.pdk.version,
                "mode": pdk_mode,
                **({"files": pdk_files} if pdk_files else {}),
            },
            "flow": flow,
            "parameters": parameters,
        },
        "workspaceBindings": {
            "inputs": input_bindings,
            "pdk": {
                "root": str(workspace.pdk.root or ""),
                "version": workspace.pdk.version,
                **({"files": pdk_file_bindings} if pdk_file_bindings else {}),
            },
        },
    }


def read_step_configuration(workspace: Any, step_id: str) -> dict[str, Any]:
    step, schemas = step_catalog(workspace, step_id)
    snapshot = _read_snapshot_metadata(workspace)
    if not schemas:
        raise WorkspaceLifecycleError(
            "step_configuration_unavailable",
            f"Flow Step has no configurable parameters: {step}",
            {
                "workspaceId": snapshot["workspaceId"],
                "workspaceRevision": snapshot["workspaceRevision"],
            },
        )
    return {
        "step": step,
        "stepId": step,
        "parameters": [_public_parameter_record(workspace, schema, step) for schema in schemas],
        "workspaceId": snapshot["workspaceId"],
        "workspaceRevision": snapshot["workspaceRevision"],
    }


def read_step_configuration_from_directory(
    target_directory: str | Path,
    step_id: str,
) -> dict[str, Any]:
    workspace = _load_committed_workspace(Path(target_directory).expanduser().resolve())
    return read_step_configuration(workspace, step_id)


def update_workspace_step_configuration(
    target_directory: str | Path,
    expected_workspace_revision: int,
    step_id: str,
    parameters: object,
    command_id: str = "",
):
    target = Path(target_directory).expanduser().resolve()
    if not target.is_dir():
        raise WorkspaceLifecycleError("workspace_missing", f"Workspace not found: {target}")
    return _run_file_transaction(
        target,
        lambda: _update_workspace_step_configuration(
            target,
            expected_workspace_revision,
            step_id,
            parameters,
            command_id,
        ),
    )


def _update_workspace_step_configuration(
    target: Path,
    expected_workspace_revision: int,
    step_id: str,
    parameters: object,
    command_id: str,
):
    if not isinstance(step_id, str) or not step_id.strip() or not isinstance(parameters, dict):
        raise WorkspaceLifecycleError(
            "workspace_spec_invalid", "Step identity and parameters object are required"
        )
    patch = {str(key): value for key, value in parameters.items()}
    fingerprint = workspace_command_fingerprint(
        "step_configuration",
        {"stepId": step_id, "parameters": patch},
        {},
        expected_workspace_revision,
    )
    if command_id and command_retry_matches(target, command_id, fingerprint):
        return _load_committed_workspace(target)

    workspace = _load_committed_workspace(target)
    snapshot = ensure_engineering_snapshot(workspace)
    if snapshot["workspaceRevision"] != expected_workspace_revision:
        raise WorkspaceLifecycleError(
            "revision_conflict",
            "Workspace Revision does not match",
            {
                "expectedWorkspaceRevision": expected_workspace_revision,
                "actualWorkspaceRevision": snapshot["workspaceRevision"],
            },
        )
    step, schemas = step_catalog(workspace, step_id)
    allowed = {schema.param: schema for schema in schemas}
    changed = False
    changed_schemas = []
    for parameter, value in patch.items():
        schema = lookup_schema(parameter)
        if schema is None or schema.pdk_target is not None:
            raise WorkspaceLifecycleError("unknown_parameter", f"Unknown parameter: {parameter}")
        if parameter not in allowed:
            raise WorkspaceLifecycleError(
                "parameter_not_applicable",
                f"Parameter {parameter} is not configurable at {step}",
            )
        normalized, type_error = validate_schema_type(value, schema)
        errors = [type_error] if type_error else _value_errors(workspace, normalized, schema)
        if errors:
            raise WorkspaceLifecycleError("invalid_parameter", str(errors[0]))
        scope = step if is_step_scoped(schema) else None
        if workspace_param_value(workspace, schema, step=scope) != normalized:
            update_workspace_param_value(workspace, schema, normalized, step=scope)
            changed = True
            changed_schemas.append(schema)

    if not changed:
        write_workspace_command(
            target,
            command_id,
            fingerprint,
            snapshot["workspaceId"],
            snapshot["workspaceRevision"],
        )
        return workspace
    if not save_parameter(workspace.parameters):
        raise OSError("Failed to save Workspace parameters")
    from chipcompiler.data import refresh_workspace_config
    from chipcompiler.data.flow.options import sync_flow_options_projection

    refresh_workspace_config(workspace)
    sync_flow_options_projection(workspace, persist=True)
    _prune_macro_location_after_write(workspace, set(patch))
    if changed_schemas and all(schema.output_only for schema in changed_schemas):
        updated = refresh_engineering_snapshot(
            workspace,
            workspace_id=snapshot["workspaceId"],
            cause="workspace.output_step_configuration_updated",
        )
        write_workspace_command(
            target,
            command_id,
            fingerprint,
            updated["workspaceId"],
            updated["workspaceRevision"],
        )
        return _load_committed_workspace(target)
    # A workspace-wide value edited from this step's view may feed earlier steps.
    affected = [
        step,
        *(
            workspace_param_step(schema, workspace, step if is_step_scoped(schema) else None)
            for schema in changed_schemas
        ),
    ]
    first_step = earliest_flow_step(workspace, [name for name in affected if name is not None])
    invalidate_from(EngineFlow(workspace), first_step)
    updated = invalidate_engineering_snapshot(
        workspace,
        workspace_id=snapshot["workspaceId"],
        cause="workspace.step_configuration_updated",
        first_invalidated_step=first_step,
    )
    write_workspace_command(
        target,
        command_id,
        fingerprint,
        updated["workspaceId"],
        updated["workspaceRevision"],
    )
    return _load_committed_workspace(target)


def _public_parameter_record(workspace: Any, schema, step: str) -> dict[str, Any]:
    pdk = workspace.pdk.name
    record = {
        "param": schema.param,
        "type": schema.type,
        "value": workspace_param_value(
            workspace, schema, step=step if is_step_scoped(schema) else None
        ),
        "default": deepcopy(schema.default_for(pdk)),
        "applies": schema.applies,
        **({"output_only": True} if schema.output_only else {}),
        "description": schema.description,
        "display_key": display_key_for(schema.param),
        "knob_id": knob_id_for(schema.param),
    }
    for field in ("range", "choices", "unit"):
        value = schema.choices_for(pdk) if field == "choices" else getattr(schema, field)
        if value is not None:
            record[field] = list(value) if isinstance(value, tuple) else value
    return record


def read_workspace_configuration_from_directory(
    target_directory: str | Path,
) -> dict[str, Any]:
    target = Path(target_directory).expanduser().resolve()
    workspace = load_workspace(target, read_only=True)
    if workspace is None:
        raise WorkspaceLifecycleError("workspace_missing", f"Workspace not found: {target}")
    return read_workspace_configuration(workspace)


def _workspace_inputs(workspace: Any) -> tuple[list[dict[str, str]], dict[str, str]]:
    values = []
    input_mode = workspace.parameters.data.get("_input_mode")
    if input_mode == "def":
        pass
    elif input_mode == "postSynthesis" and workspace.design.origin_verilog is not None:
        values.append(("netlist", workspace.design.origin_verilog))
    elif workspace.design.input_filelist is not None:
        values.append(("filelist", workspace.design.input_filelist))
    elif workspace.design.origin_verilog is not None:
        role = "netlist" if workspace.design.origin_def is not None else "rtl"
        values.append((role, workspace.design.origin_verilog))
    for role, path in (
        ("def", workspace.design.origin_def),
        ("goldenNetlist", workspace.design.golden_verilog),
        ("sdc", workspace.pdk.sdc),
        ("spef", workspace.pdk.spef),
    ):
        if path is not None:
            values.append((role, path))
    return (
        [{"inputId": role, "role": role} for role, _path in values],
        {role: str(path) for role, path in values},
    )


def _workspace_pdk_files(workspace: Any) -> tuple[list[dict[str, str]], dict[str, str]]:
    grouped = {
        "tech": [workspace.pdk.tech] if workspace.pdk.tech else [],
        "lef": list(workspace.pdk.lefs),
        "liberty": list(workspace.pdk.libs),
        "mapping": [workspace.pdk.mapping_file] if workspace.pdk.mapping_file else [],
    }
    refs = []
    bindings = {}
    for role, paths in grouped.items():
        for index, path in enumerate(paths):
            file_id = role if len(paths) == 1 else f"{role}-{index}"
            refs.append({"fileId": file_id, "role": role})
            bindings[file_id] = str(path)
    return refs, bindings


def _read_snapshot_metadata(workspace: Any) -> dict[str, Any]:
    try:
        snapshot = open_workspace_snapshot(workspace)
    except EngineeringSnapshotError as exc:
        raise WorkspaceLifecycleError(exc.code, str(exc)) from exc
    return {
        "workspaceId": snapshot["workspaceId"],
        "workspaceRevision": snapshot["workspaceRevision"],
    }


def _flow_id(names: list[str]) -> str:
    for flow_id, builder in get_flow_builders().items():
        candidate = [str(getattr(step, "value", step)) for step, _tool, _state in builder()]
        if candidate == names:
            return flow_id
        if flow_id == "rtl2gds" and names:
            start = next(
                (index for index, value in enumerate(candidate) if value == names[0]), None
            )
            if start is not None and candidate[start : start + len(names)] == names:
                return flow_id
    return "custom"


def _run_file_transaction(target: Path, apply):
    transaction = WorkspaceFileTransaction.begin(target, _workspace_file_paths(target))
    try:
        result = apply()
        transaction.commit()
        return result
    except BaseException:
        transaction.rollback()
        raise


def _workspace_file_paths(target: Path) -> list[Path]:
    paths = [
        target / "home" / "params.toml",
        target / "home" / "flow.json",
        target / "home" / SNAPSHOT_FILENAME,
        target / "home" / STALE_SNAPSHOT_FILENAME,
        target / "home" / "workspace-commands.json",
    ]
    paths.extend(path for key, path in workspace_config_paths(target).items() if key != "dir")
    return paths
