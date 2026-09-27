"""Transport-neutral Workspace flow reset primitives."""

import shutil
from pathlib import Path
from typing import Any

from chipcompiler.engine.snapshot import commit_engineering_snapshot, read_engineering_snapshot
from chipcompiler.engine.workspace_lifecycle import (
    WorkspaceLifecycleError,
    _command_retry_matches,
    _load_committed_workspace,
    _workspace_command_fingerprint,
    _write_workspace_command,
)
from chipcompiler.utility.path import path_is_within


def build_flow_for_workspace(workspace: Any, *, create_step_workspaces: bool = True):
    import chipcompiler.rtl2gds as rtl2gds_api
    from chipcompiler.engine import EngineFlow

    engine_flow = EngineFlow(workspace=workspace)
    if not engine_flow.has_init():
        parameters = getattr(getattr(workspace, "parameters", None), "data", None)
        persisted_flow = parameters.get("_flow") if isinstance(parameters, dict) else None
        skip = rtl2gds_api.resolve_skip_steps(
            persisted_flow if isinstance(persisted_flow, dict) else None
        )
        for step, tool, state in rtl2gds_api.build_rtl2gds_flow(skip=skip):
            engine_flow.add_step(step=step, tool=tool, state=state)
    if create_step_workspaces:
        engine_flow.create_step_workspaces()
    return engine_flow


def prepare_steps_for_rerun(workspace: Any, engine_flow: Any, workspace_steps: list[Any]) -> None:
    workspace_root = Path(workspace.directory).resolve()
    unique_steps = []
    known_step_keys = set()
    for workspace_step in workspace_steps:
        key = (
            str(getattr(workspace_step, "name", "")),
            str(getattr(workspace_step, "tool", "")),
        )
        if key in known_step_keys:
            continue
        known_step_keys.add(key)
        unique_steps.append(workspace_step)

    artifact_directories = []
    known_directories = set()
    for workspace_step in unique_steps:
        for directory in _step_artifact_dirs(workspace_step):
            resolved = _validate_step_artifact_dir(
                workspace_root, directory, str(getattr(workspace_step, "name", ""))
            )
            if resolved in known_directories:
                continue
            known_directories.add(resolved)
            artifact_directories.append((workspace_step.name, directory))
    for step_name, directory in artifact_directories:
        _clear_step_artifact_dir(workspace_root, directory, step_name)

    updated_record = False
    for workspace_step in unique_steps:
        record = engine_flow.get_step(workspace_step.name, workspace_step.tool)
        if record is None:
            continue
        record.update({"state": "Unstart", "runtime": "", "peak memory (mb)": 0, "info": {}})
        updated_record = True
    if updated_record and not engine_flow.save():
        raise WorkspaceLifecycleError("workspace_reset_failed", "Failed to persist flow reset")
    for workspace_step in unique_steps:
        _reset_step_subflow(workspace_step)
        _reset_step_checklist(workspace_step)


def reset_workspace_flow(
    target_directory: str | Path,
    expected_workspace_revision: int,
    *,
    command_id: str = "",
    blocking: bool = True,
):
    target = Path(target_directory).expanduser().resolve()
    from chipcompiler.engine.reconcile import _workspace_lock

    with _workspace_lock(target, blocking=blocking):
        return _reset_workspace_flow(target, expected_workspace_revision, command_id=command_id)


def _reset_workspace_flow(
    target: Path,
    expected_workspace_revision: int,
    *,
    command_id: str,
):
    fingerprint = _workspace_command_fingerprint(
        "reset_flow", {"directory": str(target)}, {}, expected_workspace_revision
    )
    if command_id and _command_retry_matches(target, command_id, fingerprint):
        return _load_committed_workspace(target)
    workspace = _load_committed_workspace(target)
    snapshot = read_engineering_snapshot(workspace)
    if snapshot["workspaceRevision"] != expected_workspace_revision:
        raise WorkspaceLifecycleError(
            "revision_conflict",
            "Workspace Revision does not match",
            {
                "expectedWorkspaceRevision": expected_workspace_revision,
                "actualWorkspaceRevision": snapshot["workspaceRevision"],
            },
        )
    engine_flow = build_flow_for_workspace(workspace)
    from chipcompiler.data import prepare_workspace_for_rerun

    prepare_workspace_for_rerun(workspace, engine_flow, preserve_user_inputs=True)
    updated = commit_engineering_snapshot(
        workspace,
        workspace_id=snapshot["workspaceId"],
        cause="workspace.flow_reset",
    )
    _write_workspace_command(
        target,
        command_id,
        fingerprint,
        updated["workspaceId"],
        updated["workspaceRevision"],
    )
    return _load_committed_workspace(target)


def _reset_step_subflow(workspace_step: Any) -> None:
    from chipcompiler.utility import json_read, json_write

    subflow = getattr(workspace_step, "subflow", None)
    path = getattr(subflow, "path", None)
    if not path:
        return
    subflow_path = Path(path)
    data = json_read(subflow_path)
    steps = data.get("steps", []) if isinstance(data, dict) else []
    if not isinstance(steps, list):
        return
    for step in steps:
        if isinstance(step, dict):
            step.update({"state": "Unstart", "runtime": "", "peak memory (mb)": 0, "info": {}})
    if not json_write(subflow_path, {"path": str(subflow_path), "steps": steps}):
        raise WorkspaceLifecycleError("workspace_reset_failed", "Failed to reset subflow")
    subflow.steps = steps


def _reset_step_checklist(workspace_step: Any) -> None:
    from chipcompiler.data import Checklist

    checklist = getattr(workspace_step, "checklist", None)
    path = getattr(checklist, "path", None)
    if not path:
        return
    Checklist(Path(path)).replace([])
    checklist.checklist = []


def _step_artifact_dirs(step: Any) -> tuple[Path, ...]:
    directories = []
    for field in ("output", "data", "feature", "analysis", "report", "log"):
        value = getattr(step, field, {})
        directory = value.get("dir") if isinstance(value, dict) else getattr(value, "dir", None)
        if directory:
            directories.append(Path(directory))
    return tuple(dict.fromkeys(directories))


def _clear_step_artifact_dir(workspace_root: Path, directory: Path, step_name: str) -> None:
    _validate_step_artifact_dir(workspace_root, directory, step_name)
    if directory.exists():
        if not directory.is_dir():
            raise WorkspaceLifecycleError(
                "workspace_reset_failed", f"Step artifact is not a directory: {step_name}"
            )
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=True)


def _validate_step_artifact_dir(workspace_root: Path, directory: Path, step_name: str) -> Path:
    resolved = directory.resolve()
    if (
        resolved == workspace_root
        or not path_is_within(resolved, workspace_root)
        or directory.is_symlink()
        or directory.exists()
        and not directory.is_dir()
    ):
        raise WorkspaceLifecycleError(
            "workspace_reset_failed", f"Step artifact escapes Workspace: {step_name}"
        )
    return resolved
