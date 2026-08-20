"""Rerun preparation: atomic record invalidation plus artifact cleanup.

Extracted from workspace_api.py so the state-transition machinery lives in a
focused module and the API class stays an adapter. `prepare_steps_for_rerun`
is one all-or-nothing transition: validate artifact directories, snapshot
affected flow records, apply the target reset plus dependent state
invalidation, persist once, and only then delete the target's artifacts.
"""

import shutil
from pathlib import Path

from chipcompiler.utility.path import path_is_within


def _runtime_api_error(message: str):
    # Local import: workspace_api imports this module, so the shared error
    # type is resolved lazily to keep the dependency one-directional.
    from chipcompiler.runtime.workspace_api import RuntimeApiError

    return RuntimeApiError("command_failed", message)


def rerun_affected_steps(engine_flow, workspace_step, *, reset_dependents: bool):
    if not reset_dependents:
        return [workspace_step]
    workspace_steps = list(getattr(engine_flow, "workspace_steps", []))
    try:
        start_index = workspace_steps.index(workspace_step)
    except ValueError:
        return [workspace_step]
    return workspace_steps[start_index:]


def prepare_step_for_rerun(workspace, engine_flow, workspace_step) -> None:
    prepare_steps_for_rerun(workspace, engine_flow, [workspace_step])


def prepare_steps_for_rerun(
    workspace,
    engine_flow,
    workspace_steps,
    *,
    invalidate_only_steps=(),
) -> None:
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
                workspace_root,
                directory,
                workspace_step.name,
            )
            if resolved in known_directories:
                continue
            known_directories.add(resolved)
            artifact_directories.append((workspace_step.name, directory))

    # One all-or-nothing state transition: apply the full reset for the
    # rerun targets and the state-only invalidation for their dependents,
    # then persist once. A failed save restores the record snapshots so
    # neither disk nor the live session is left half-mutated, and no
    # artifact is deleted before the new states are durable.
    snapshots = []
    for workspace_step in (*unique_steps, *invalidate_only_steps):
        record = engine_flow.get_step(workspace_step.name, workspace_step.tool)
        if record is not None:
            snapshots.append((record, dict(record)))
    for workspace_step in unique_steps:
        record = engine_flow.get_step(workspace_step.name, workspace_step.tool)
        if record is None:
            continue
        record.update(
            {
                "state": "Unstart",
                "runtime": "",
                "peak memory (mb)": 0,
                "info": {},
            }
        )
    for workspace_step in invalidate_only_steps:
        record = engine_flow.get_step(workspace_step.name, workspace_step.tool)
        if record is None:
            continue
        record.update({"state": "Unstart", "runtime": "", "peak memory (mb)": 0})
    if snapshots and not engine_flow.save():
        for record, snapshot in snapshots:
            record.clear()
            record.update(snapshot)
        raise _runtime_api_error("failed to persist step invalidation; refusing to modify outputs")

    # Post-save cleanup can still fail midway (artifact delete, subflow or
    # checklist reset). Cleanup is irreversible for steps already cleared,
    # so those steps keep their persisted Unstart records (their outputs are
    # gone); only steps not yet touched roll back to their snapshots.
    try:
        for workspace_step in unique_steps:
            for step_name, directory in artifact_directories:
                if step_name != workspace_step.name:
                    continue
                _clear_step_artifact_dir(
                    workspace_root,
                    directory,
                    step_name,
                )
            _reset_step_subflow(workspace_step)
            _reset_step_checklist(workspace_step)
    except Exception:
        # Steps up to and including the one mid-cleanup have lost artifacts;
        # their persisted Unstart must stay. Later steps roll back intact.
        cleaned = {
            str(getattr(step, "name", ""))
            for step in unique_steps[: unique_steps.index(workspace_step) + 1]
        }
        for record, snapshot in snapshots:
            if record.get("name") in cleaned:
                continue
            record.clear()
            record.update(snapshot)
        engine_flow.save()
        raise


def _reset_step_subflow(workspace_step) -> None:
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
        if not isinstance(step, dict):
            continue
        step.update(
            {
                "state": "Unstart",
                "runtime": "",
                "peak memory (mb)": 0,
                "info": {},
            }
        )
    json_write(subflow_path, {"path": str(subflow_path), "steps": steps})
    subflow.steps = steps


def _reset_step_checklist(workspace_step) -> None:
    from chipcompiler.data import Checklist

    checklist = getattr(workspace_step, "checklist", None)
    path = getattr(checklist, "path", None)
    if not path:
        return
    checklist_path = Path(path)
    Checklist(checklist_path).replace([])
    checklist.checklist = []


def _step_artifact_dirs(step) -> tuple[Path, ...]:
    directories: list[Path] = []
    for field in ("output", "data", "feature", "analysis", "report", "log"):
        value = getattr(step, field, {})
        directory = value.get("dir") if isinstance(value, dict) else getattr(value, "dir", None)
        if directory:
            directories.append(Path(directory))
    return tuple(dict.fromkeys(directories))


def _clear_step_artifact_dir(
    workspace_root: Path,
    directory: Path,
    step_name: str,
) -> None:
    _validate_step_artifact_dir(workspace_root, directory, step_name)
    if directory.exists():
        if not directory.is_dir():
            raise _runtime_api_error(f"step artifact is not a directory: {step_name}")
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=True)


def _validate_step_artifact_dir(
    workspace_root: Path,
    directory: Path,
    step_name: str,
) -> Path:
    resolved = directory.resolve()
    if (
        resolved == workspace_root
        or not path_is_within(resolved, workspace_root)
        or directory.is_symlink()
    ):
        raise _runtime_api_error(f"step artifact escapes workspace: {step_name}")
    if directory.exists() and not directory.is_dir():
        raise _runtime_api_error(f"step artifact is not a directory: {step_name}")
    return resolved
