from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from chipcompiler.engine.snapshot_qor import (
    build_qor_snapshot_extension,
    unavailable_qor_snapshot_extension,
    validate_qor_snapshot_extension,
)
from chipcompiler.utility import JsonReadError, json_read, json_read_strict, json_write

SNAPSHOT_SCHEMA_VERSION = 2
SNAPSHOT_V3_SCHEMA_VERSION = 3
SUPPORTED_SNAPSHOT_SCHEMA_VERSIONS = frozenset(
    {SNAPSHOT_SCHEMA_VERSION, SNAPSHOT_V3_SCHEMA_VERSION}
)
SNAPSHOT_FILENAME = "engineering-snapshot.json"
STALE_SNAPSHOT_FILENAME = "engineering-snapshot.stale.json"
SNAPSHOT_V2_TO_V3_MIGRATION_CAUSE = "snapshot.migrated.v2_to_v3"


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
        snapshot = _read_snapshot(path)
        if snapshot["schemaVersion"] != SNAPSHOT_SCHEMA_VERSION:
            raise EngineeringSnapshotError("production Snapshot schema is still v2")
        return snapshot
    return create_engineering_snapshot(workspace, cause="workspace.migrated")


def read_engineering_snapshot(workspace: Any) -> dict[str, Any]:
    return _read_snapshot(_snapshot_path(workspace))


def read_engineering_snapshot_from_directory(directory: str | Path) -> dict[str, Any]:
    return _read_snapshot(Path(directory).expanduser().resolve() / "home" / SNAPSHOT_FILENAME)


def read_stale_engineering_snapshot(workspace: Any) -> dict[str, Any] | None:
    path = _stale_snapshot_path(workspace)
    return _read_snapshot(path) if path.is_file() else None


def migrate_engineering_snapshot(
    workspace: Any,
    *,
    expected_workspace_revision: int | None = None,
    cause: str = SNAPSHOT_V2_TO_V3_MIGRATION_CAUSE,
) -> dict[str, Any]:
    """Explicitly migrate one v2 Snapshot to the prepared v3 contract.

    Normal Snapshot producers remain pinned to v2. This write-only seam is the
    only path that emits v3 until ECC and Studio switch the production contract.
    """
    current = _read_snapshot(_snapshot_path(workspace))
    if current["schemaVersion"] != SNAPSHOT_SCHEMA_VERSION:
        raise EngineeringSnapshotError("Snapshot migration requires schemaVersion 2")
    if (
        expected_workspace_revision is not None
        and current["workspaceRevision"] != expected_workspace_revision
    ):
        raise EngineeringSnapshotError(
            "Workspace Revision does not match before Snapshot migration"
        )
    try:
        snapshot = _build_snapshot(
            workspace,
            workspace_id=current["workspaceId"],
            workspace_revision=current["workspaceRevision"] + 1,
            cause=cause,
            schema_version=SNAPSHOT_V3_SCHEMA_VERSION,
            strict_qor=True,
        )
    except Exception as exc:
        raise EngineeringSnapshotError(
            "failed to regenerate QoR facts for Snapshot migration"
        ) from exc
    if isinstance(current.get("stalePredecessor"), dict):
        snapshot["stalePredecessor"] = deepcopy(current["stalePredecessor"])
    _write_snapshot(_snapshot_path(workspace), snapshot)
    return snapshot


migrate_engineering_snapshot_v2_to_v3 = migrate_engineering_snapshot


def commit_engineering_snapshot(
    workspace: Any,
    *,
    workspace_id: str,
    cause: str,
) -> dict[str, Any]:
    current = read_engineering_snapshot(workspace)
    if current["schemaVersion"] != SNAPSHOT_SCHEMA_VERSION:
        raise EngineeringSnapshotError("production Snapshot schema is still v2")
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
    _write_snapshot(_snapshot_path(workspace), snapshot)
    if isinstance(stale, dict) and "stalePredecessor" not in snapshot:
        _stale_snapshot_path(workspace).unlink(missing_ok=True)
    return snapshot


def invalidate_engineering_snapshot(
    workspace: Any,
    *,
    workspace_id: str,
    cause: str,
    first_invalidated_step: str | None = None,
) -> dict[str, Any]:
    current = read_engineering_snapshot(workspace)
    if current["schemaVersion"] != SNAPSHOT_SCHEMA_VERSION:
        raise EngineeringSnapshotError("production Snapshot schema is still v2")
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
    schema_version: int = SNAPSHOT_SCHEMA_VERSION,
    strict_qor: bool = False,
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
    try:
        from chipcompiler.analysis.qor import build_qor_analysis

        qor_extension = build_qor_snapshot_extension(
            build_qor_analysis(workspace),
            artifacts,
        )
    except Exception as exc:
        if strict_qor:
            raise
        qor_extension = unavailable_qor_snapshot_extension(str(exc))
    return {
        "schemaVersion": schema_version,
        "workspaceId": workspace_id,
        "workspaceRevision": workspace_revision,
        "cause": cause,
        "flow": flow,
        "parameters": _data_mapping(getattr(workspace, "parameters", None)),
        "checklist": checklist if isinstance(checklist, dict) else {},
        "analysis": analysis,
        "metrics": deepcopy(qor_assessment["metrics"]),
        "qorAssessment": qor_assessment,
        "qorSnapshotExtension": qor_extension,
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
        or snapshot.get("schemaVersion") not in SUPPORTED_SNAPSHOT_SCHEMA_VERSIONS
        or not isinstance(snapshot.get("workspaceId"), str)
        or not snapshot["workspaceId"]
        or isinstance(snapshot.get("workspaceRevision"), bool)
        or not isinstance(snapshot.get("workspaceRevision"), int)
        or snapshot["workspaceRevision"] < 1
        or (
            snapshot.get("schemaVersion") == SNAPSHOT_V3_SCHEMA_VERSION
            and not validate_qor_snapshot_extension(snapshot.get("qorSnapshotExtension"))
        )
    ):
        raise EngineeringSnapshotError(f"invalid Engineering Snapshot: {path}")
    return snapshot
