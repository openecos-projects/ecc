from pathlib import Path
from typing import Any

from chipcompiler.cli.project.params import (
    _validate_schema_type,
    list_schemas,
    lookup_schema,
    validate_value,
)
from chipcompiler.cli.project.workspace_params import (
    update_workspace_param_value,
    workspace_param_value,
)
from chipcompiler.data import load_workspace, save_parameter
from chipcompiler.data.workspace import workspace_config_paths
from chipcompiler.engine.flow import EngineFlow
from chipcompiler.engine.rerun import invalidate_from
from chipcompiler.engine.snapshot import (
    SNAPSHOT_FILENAME,
    STALE_SNAPSHOT_FILENAME,
    ensure_engineering_snapshot,
    invalidate_engineering_snapshot,
)
from chipcompiler.rtl2gds import get_flow_builders

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
    before = _snapshot_files(_workspace_file_paths(target))
    try:
        return _update_workspace_configuration(
            target,
            expected_workspace_revision,
            configuration,
            workspace_bindings,
            command_id,
        )
    except BaseException:
        _restore_files(before)
        raise


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
        normalized, type_error = _validate_schema_type(value, schema)
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
    return {
        "workspaceSpec": {
            "schemaVersion": 1,
            "design": {
                "name": workspace.design.name,
                "topModule": workspace.design.top_module,
                "clockPort": str(workspace.parameters.data.get("clock", "")),
            },
            "inputMode": "postSynthesis" if workspace.design.origin_def is not None else "rtl",
            "inputs": inputs,
            "pdk": {
                "familyId": workspace.pdk.name,
                "version": workspace.pdk.version,
                "mode": "default",
            },
            "flow": flow,
            "parameters": parameters,
        },
        "workspaceBindings": {
            "inputs": input_bindings,
            "pdk": {
                "root": str(workspace.pdk.root or ""),
                "version": workspace.pdk.version,
            },
        },
    }


def read_workspace_configuration_from_directory(
    target_directory: str | Path,
) -> dict[str, Any]:
    target = Path(target_directory).expanduser().resolve()
    workspace = load_workspace(target)
    if workspace is None:
        raise WorkspaceLifecycleError("workspace_missing", f"Workspace not found: {target}")
    return read_workspace_configuration(workspace)


def _workspace_inputs(workspace: Any) -> tuple[list[dict[str, str]], dict[str, str]]:
    values = []
    if workspace.design.input_filelist is not None:
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


def _flow_id(names: list[str]) -> str:
    for flow_id, builder in get_flow_builders().items():
        candidate = [str(getattr(step, "value", step)) for step, _tool, _state in builder()]
        if candidate == names:
            return flow_id
    return "custom"


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


def _snapshot_files(paths: list[Path]) -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.is_file() else None for path in paths}


def _restore_files(snapshot: dict[Path, bytes | None]) -> None:
    for path, content in snapshot.items():
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
