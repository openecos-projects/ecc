from copy import deepcopy
from pathlib import Path
from typing import Any

from chipcompiler.data import load_workspace, save_parameter
from chipcompiler.data.parameter_schema import (
    list_schemas,
    lookup_schema,
    validate_schema_type,
    validate_value,
)
from chipcompiler.data.workspace import workspace_config_paths
from chipcompiler.data.workspace_parameters import (
    update_workspace_param_value,
    workspace_param_value,
)
from chipcompiler.data.workspace_transaction import WorkspaceFileTransaction
from chipcompiler.engine.flow import EngineFlow
from chipcompiler.engine.rerun import invalidate_from
from chipcompiler.engine.snapshot import (
    SNAPSHOT_FILENAME,
    STALE_SNAPSHOT_FILENAME,
    EngineeringSnapshotError,
    ensure_engineering_snapshot,
    invalidate_engineering_snapshot,
    read_engineering_snapshot,
)
from chipcompiler.rtl2gds import get_flow_builders, normalize_flow_step

from .workspace_lifecycle import (
    WorkspaceLifecycleError,
    _command_retry_matches,
    _load_committed_workspace,
    _workspace_command_fingerprint,
    _write_workspace_command,
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
    fingerprint = _workspace_command_fingerprint(
        "configuration", config, workspace_bindings, expected_workspace_revision
    )
    if command_id and _command_retry_matches(target, command_id, fingerprint):
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
    for parameter, value in parameters.items():
        schema = lookup_schema(parameter)
        if schema is None or schema.pdk_target is not None:
            raise WorkspaceLifecycleError("unknown_parameter", f"Unknown parameter: {parameter}")
        normalized, type_error = validate_schema_type(value, schema)
        errors = [type_error] if type_error else validate_value(normalized, schema)
        if errors:
            raise WorkspaceLifecycleError("invalid_parameter", str(errors[0]))
        if workspace_param_value(workspace, schema) != normalized:
            update_workspace_param_value(workspace, schema, normalized)
            changed = True

    if not changed:
        _write_workspace_command(
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

    refresh_workspace_config(workspace)
    flow = EngineFlow(workspace)
    steps = workspace.flow.steps()
    if steps:
        invalidate_from(flow, str(steps[0]["name"]))
    updated = invalidate_engineering_snapshot(
        workspace,
        workspace_id=current["workspaceId"],
        cause="workspace.configuration_updated",
    )
    _write_workspace_command(
        target,
        command_id,
        fingerprint,
        updated["workspaceId"],
        updated["workspaceRevision"],
    )
    return _load_committed_workspace(target)


def read_workspace_configuration(workspace: Any) -> dict[str, Any]:
    parameters = {}
    for schema in list_schemas():
        if schema.pdk_target is not None:
            continue
        try:
            parameters[schema.param] = workspace_param_value(workspace, schema)
        except (OSError, ValueError):
            continue
    steps = workspace.flow.steps()
    flow_names = [str(step.get("name", "")) for step in steps if step.get("name")]
    flow = {"flowId": _flow_id(flow_names)}
    if flow_names:
        flow.update({"fromStepId": flow_names[0], "throughStepId": flow_names[-1]})
    inputs, input_bindings = _workspace_inputs(workspace)
    pdk_mode = "manual" if workspace.parameters.data.get("pdk_config") else "default"
    pdk_files, pdk_file_bindings = (
        _workspace_pdk_files(workspace) if pdk_mode == "manual" else ([], {})
    )
    snapshot = _read_snapshot_metadata(workspace)
    return {
        "workspaceId": snapshot["workspaceId"],
        "workspaceRevision": snapshot["workspaceRevision"],
        "workspaceSpec": {
            "schemaVersion": 1,
            "design": {
                "name": workspace.design.name,
                "topModule": workspace.design.top_module,
                "clockPort": str(workspace.parameters.data.get("clock", "")),
            },
            "inputMode": workspace.parameters.data.get("_input_mode")
            if workspace.parameters.data.get("_input_mode") in {"rtl", "postSynthesis"}
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
    step, schemas = _step_catalog(workspace, step_id)
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
        "parameters": [_public_parameter_record(workspace, schema) for schema in schemas],
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
    fingerprint = _workspace_command_fingerprint(
        "step_configuration",
        {"stepId": step_id, "parameters": patch},
        {},
        expected_workspace_revision,
    )
    if command_id and _command_retry_matches(target, command_id, fingerprint):
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
    step, schemas = _step_catalog(workspace, step_id)
    allowed = {schema.param: schema for schema in schemas}
    changed = False
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
        errors = [type_error] if type_error else validate_value(normalized, schema)
        if errors:
            raise WorkspaceLifecycleError("invalid_parameter", str(errors[0]))
        if workspace_param_value(workspace, schema) != normalized:
            update_workspace_param_value(workspace, schema, normalized)
            changed = True

    if not changed:
        _write_workspace_command(
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

    refresh_workspace_config(workspace)
    invalidate_from(EngineFlow(workspace), step)
    updated = invalidate_engineering_snapshot(
        workspace,
        workspace_id=snapshot["workspaceId"],
        cause="workspace.step_configuration_updated",
        first_invalidated_step=step,
    )
    _write_workspace_command(
        target,
        command_id,
        fingerprint,
        updated["workspaceId"],
        updated["workspaceRevision"],
    )
    return _load_committed_workspace(target)


def _step_catalog(workspace: Any, step_id: str):
    identity = normalize_flow_step(step_id).casefold()
    steps = [str(step.get("name", "")) for step in workspace.flow.steps() if step.get("name")]
    step = next(
        (candidate for candidate in steps if normalize_flow_step(candidate).casefold() == identity),
        None,
    )
    if step is None:
        raise WorkspaceLifecycleError("unknown_flow_step", f"Flow Step not found: {step_id}")
    first = normalize_flow_step(steps[0]).casefold()
    schemas = tuple(
        schema
        for schema in list_schemas()
        if schema.pdk_target is None
        and (
            normalize_flow_step(schema.applies).casefold() == identity
            or (schema.applies == "all" and identity == first)
        )
    )
    return step, schemas


def _public_parameter_record(workspace: Any, schema) -> dict[str, Any]:
    record = {
        "param": schema.param,
        "type": schema.type,
        "value": workspace_param_value(workspace, schema),
        "default": deepcopy(schema.default),
        "applies": schema.applies,
        "description": schema.description,
    }
    for field in ("range", "choices", "unit"):
        value = getattr(schema, field)
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
    if input_mode == "postSynthesis" and workspace.design.origin_verilog is not None:
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
        snapshot = read_engineering_snapshot(workspace)
    except (EngineeringSnapshotError, OSError):
        return {"workspaceId": None, "workspaceRevision": None}
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
