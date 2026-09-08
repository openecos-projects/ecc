from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from chipcompiler.utility import JsonReadError, json_read, json_read_strict, json_write

SNAPSHOT_SCHEMA_VERSION = 2
SNAPSHOT_FILENAME = "engineering-snapshot.json"
STALE_SNAPSHOT_FILENAME = "engineering-snapshot.stale.json"


class EngineeringSnapshotError(RuntimeError):
    pass


def create_engineering_snapshot(
    workspace: Any,
    *,
    workspace_id: str | None = None,
    workspace_revision: int = 1,
    cause: str = "workspace.created",
) -> dict[str, Any]:
    snapshot = _build_snapshot(
        workspace,
        workspace_id=workspace_id or f"workspace-{uuid4().hex}",
        workspace_revision=workspace_revision,
        cause=cause,
    )
    _write_snapshot(_snapshot_path(workspace), snapshot)
    return snapshot


def ensure_engineering_snapshot(workspace: Any) -> dict[str, Any]:
    path = _snapshot_path(workspace)
    if path.is_file():
        return _read_snapshot(path)
    return create_engineering_snapshot(workspace, cause="workspace.migrated")


def read_engineering_snapshot(workspace: Any) -> dict[str, Any]:
    return _read_snapshot(_snapshot_path(workspace))


def read_engineering_snapshot_from_directory(directory: str | Path) -> dict[str, Any]:
    return _read_snapshot(Path(directory).expanduser().resolve() / "home" / SNAPSHOT_FILENAME)


def read_stale_engineering_snapshot(workspace: Any) -> dict[str, Any] | None:
    path = _stale_snapshot_path(workspace)
    return _read_snapshot(path) if path.is_file() else None


def commit_engineering_snapshot(
    workspace: Any,
    *,
    workspace_id: str,
    cause: str,
) -> dict[str, Any]:
    current = read_engineering_snapshot(workspace)
    if current["workspaceId"] != workspace_id:
        raise EngineeringSnapshotError("Workspace identity changed before commit")
    snapshot = _build_snapshot(
        workspace,
        workspace_id=workspace_id,
        workspace_revision=current["workspaceRevision"] + 1,
        cause=cause,
    )
    stale = current.get("stalePredecessor")
    if isinstance(stale, dict):
        states = {
            str(step.get("name")): step.get("state")
            for step in snapshot.get("flow", {}).get("steps", [])
            if isinstance(step, dict) and step.get("name")
        }
        remaining = [
            step_id
            for step_id in stale.get("invalidatedStepIds", [])
            if states.get(step_id) not in {"Success", "Skipped"}
        ]
        if remaining:
            snapshot["stalePredecessor"] = {**deepcopy(stale), "invalidatedStepIds": remaining}
        else:
            _stale_snapshot_path(workspace).unlink(missing_ok=True)
    _write_snapshot(_snapshot_path(workspace), snapshot)
    return snapshot


def invalidate_engineering_snapshot(
    workspace: Any,
    *,
    workspace_id: str,
    cause: str,
    first_invalidated_step: str | None = None,
) -> dict[str, Any]:
    current = read_engineering_snapshot(workspace)
    if current["workspaceId"] != workspace_id:
        raise EngineeringSnapshotError("Workspace identity changed before invalidation")
    flow = deepcopy(current.get("flow", {}))
    steps = flow.get("steps", []) if isinstance(flow, dict) else []
    invalidated_index = 0
    if first_invalidated_step is not None:
        invalidated_index = next(
            (
                index
                for index, step in enumerate(steps)
                if isinstance(step, dict)
                and str(step.get("name", "")).casefold() == first_invalidated_step.casefold()
            ),
            -1,
        )
        if invalidated_index < 0:
            raise EngineeringSnapshotError(f"Flow Step not found: {first_invalidated_step}")
    for step in steps[invalidated_index:]:
        if isinstance(step, dict):
            step["state"] = "Unstart"
            step.pop("runtime", None)
            step.pop("peak memory (mb)", None)
    stale_path = _stale_snapshot_path(workspace)
    if not stale_path.is_file():
        _write_snapshot(stale_path, current)
    invalidated = [
        str(step["name"])
        for step in steps[invalidated_index:]
        if isinstance(step, dict) and step.get("name")
    ]
    snapshot = _build_snapshot(
        workspace,
        workspace_id=workspace_id,
        workspace_revision=current["workspaceRevision"] + 1,
        cause=cause,
    )
    snapshot["flow"] = flow
    snapshot["stalePredecessor"] = {
        "workspaceRevision": current["workspaceRevision"],
        "invalidatedStepIds": invalidated,
    }
    _write_snapshot(_snapshot_path(workspace), snapshot)
    return snapshot


def _build_snapshot(
    workspace: Any,
    *,
    workspace_id: str,
    workspace_revision: int,
    cause: str,
) -> dict[str, Any]:
    flow_owner = getattr(workspace, "flow", None)
    flow = _data_mapping(flow_owner)
    if not flow and flow_owner is not None:
        steps = flow_owner.steps()
        flow = {"steps": deepcopy(steps)} if steps else {}
    home = _data_mapping(getattr(workspace, "home", None))
    checklist_path = home.get("checklist")
    checklist = json_read(checklist_path) if isinstance(checklist_path, (str, Path)) else {}
    from chipcompiler.engine.analysis import build_workspace_analysis
    from chipcompiler.engine.qor import build_workspace_qor_assessment
    from chipcompiler.engine.signoff_assessment import build_signoff_assessment

    analysis, artifacts = build_workspace_analysis(workspace, workspace_id)
    qor_assessment = build_workspace_qor_assessment(analysis)
    return {
        "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "workspaceId": workspace_id,
        "workspaceRevision": workspace_revision,
        "cause": cause,
        "flow": flow,
        "parameters": _data_mapping(getattr(workspace, "parameters", None)),
        "checklist": checklist if isinstance(checklist, dict) else {},
        "analysis": analysis,
        "metrics": deepcopy(qor_assessment["metrics"]),
        "qorAssessment": qor_assessment,
        "signoffAssessment": build_signoff_assessment(workspace),
        "artifacts": artifacts,
    }


def _snapshot_path(workspace: Any) -> Path:
    return Path(workspace.directory) / "home" / SNAPSHOT_FILENAME


def _stale_snapshot_path(workspace: Any) -> Path:
    return Path(workspace.directory) / "home" / STALE_SNAPSHOT_FILENAME


def _data_mapping(owner: Any) -> dict[str, Any]:
    data = getattr(owner, "data", {})
    return deepcopy(data) if isinstance(data, dict) else {}


def _write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not json_write(path, snapshot):
        raise EngineeringSnapshotError(f"failed to persist Engineering Snapshot: {path}")


def _read_snapshot(path: Path) -> dict[str, Any]:
    try:
        snapshot = json_read_strict(path)
    except (OSError, JsonReadError) as exc:
        raise EngineeringSnapshotError(f"invalid Engineering Snapshot: {path}") from exc
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("schemaVersion") != SNAPSHOT_SCHEMA_VERSION
        or not isinstance(snapshot.get("workspaceId"), str)
        or not snapshot["workspaceId"]
        or isinstance(snapshot.get("workspaceRevision"), bool)
        or not isinstance(snapshot.get("workspaceRevision"), int)
        or snapshot["workspaceRevision"] < 1
    ):
        raise EngineeringSnapshotError(f"invalid Engineering Snapshot: {path}")
    return snapshot
