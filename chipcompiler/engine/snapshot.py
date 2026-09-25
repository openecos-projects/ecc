import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from chipcompiler.data.checklist import workspace_checklist_path
from chipcompiler.engine.snapshot_limits import (
    CHECKLIST_READ_MAX_BYTES,
    ENGINEERING_SNAPSHOT_MAX_BYTES,
    encoded_json_size,
    read_bounded_json_object,
)
from chipcompiler.engine.snapshot_qor import (
    build_qor_snapshot_extension,
    unavailable_qor_snapshot_extension,
    validate_qor_snapshot_extension,
)
from chipcompiler.utility import JsonReadError, json_read_strict, json_write

SNAPSHOT_SCHEMA_VERSION = 6
SNAPSHOT_FILENAME = "engineering-snapshot.json"
STALE_SNAPSHOT_FILENAME = "engineering-snapshot.stale.json"
SNAPSHOT_REBUILD_REQUIRED = "snapshot_rebuild_required"
SNAPSHOT_IDENTITY_MISMATCH = "snapshot_identity_mismatch"
SNAPSHOT_REVISION_MISMATCH = "snapshot_revision_mismatch"
SNAPSHOT_OPEN_REBUILD_CAUSE = "workspace.rebuild.on_open"
SNAPSHOT_ARTIFACT_LIMIT = 4096
_CHECKLIST_PROJECTION_MAX_ITEMS = 512


class EngineeringSnapshotError(RuntimeError):
    def __init__(self, message: str, *, code: str = SNAPSHOT_REBUILD_REQUIRED):
        super().__init__(message)
        self.code = code


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
    if not path.exists() and not path.is_symlink():
        return create_engineering_snapshot(workspace, cause="workspace.migrated")
    return _read_snapshot(path)


def open_workspace_snapshot(workspace: Any) -> dict[str, Any]:
    """Open-time snapshot policy (ADR-0009), shared by every open entry point.

    A missing snapshot is rebuilt automatically (only ever writing a file
    that does not exist); a corrupt, unsupported-version, or
    identity-conflicting snapshot fails closed with the error's ``code``
    classifying the failure, leaving the existing file untouched.
    """
    path = _snapshot_path(workspace)
    if not path.exists() and not path.is_symlink():
        return create_engineering_snapshot(workspace, cause=SNAPSHOT_OPEN_REBUILD_CAUSE)
    return _read_snapshot(path)


def read_engineering_snapshot(
    workspace: Any,
    *,
    expected_workspace_id: str | None = None,
    expected_workspace_revision: int | None = None,
) -> dict[str, Any]:
    """Read the committed Snapshot projection.

    Artifacts are path references into the workspace, never versioned copies;
    readers get path-safety validation but no content fingerprinting.
    """
    snapshot = _read_snapshot(_snapshot_path(workspace))
    if expected_workspace_id is not None and snapshot["workspaceId"] != expected_workspace_id:
        raise EngineeringSnapshotError(
            "Engineering Snapshot workspace identity mismatch",
            code=SNAPSHOT_IDENTITY_MISMATCH,
        )
    if (
        expected_workspace_revision is not None
        and snapshot["workspaceRevision"] != expected_workspace_revision
    ):
        raise EngineeringSnapshotError(
            "Engineering Snapshot Workspace Revision mismatch",
            code=SNAPSHOT_REVISION_MISMATCH,
        )
    return snapshot


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
        raise EngineeringSnapshotError(
            "Workspace identity changed before commit", code=SNAPSHOT_IDENTITY_MISMATCH
        )
    snapshot = _build_snapshot(
        workspace,
        workspace_id=workspace_id,
        workspace_revision=current["workspaceRevision"] + 1,
        cause=cause,
    )
    if isinstance(current.get("workspaceSpec"), dict):
        snapshot["workspaceSpec"] = deepcopy(current["workspaceSpec"])
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
    if current["workspaceId"] != workspace_id:
        raise EngineeringSnapshotError(
            "Workspace identity changed before invalidation", code=SNAPSHOT_IDENTITY_MISMATCH
        )
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
    if isinstance(current.get("workspaceSpec"), dict):
        snapshot["workspaceSpec"] = deepcopy(current["workspaceSpec"])
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
    checklist_path = workspace_checklist_path(getattr(workspace, "directory", None))
    checklist_result = read_bounded_json_object(
        Path(checklist_path),
        CHECKLIST_READ_MAX_BYTES,
    )
    checklist = checklist_result.data if checklist_result.status == "available" else {}
    from chipcompiler.engine.analysis import collect_workspace_projections
    from chipcompiler.engine.signoff_assessment import build_signoff_assessment

    projections = collect_workspace_projections(workspace, workspace_id)
    artifacts = projections["artifacts"]
    if len(artifacts) > SNAPSHOT_ARTIFACT_LIMIT:
        raise EngineeringSnapshotError(
            f"Engineering Snapshot artifact index exceeds {SNAPSHOT_ARTIFACT_LIMIT} "
            f"entries ({len(artifacts)})"
        )
    try:
        from chipcompiler.analysis.qor import build_qor_analysis

        qor_extension = build_qor_snapshot_extension(
            build_qor_analysis(workspace),
            artifacts,
        )
    except Exception as exc:
        qor_extension = unavailable_qor_snapshot_extension(str(exc))
    return {
        "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "workspaceId": workspace_id,
        "workspaceRevision": workspace_revision,
        "cause": cause,
        "flow": flow,
        "parameters": _data_mapping(getattr(workspace, "parameters", None)),
        "metrics": projections["metrics"],
        "qorSnapshotExtension": qor_extension,
        "signoffAssessment": build_signoff_assessment(workspace, checklist=checklist),
        "timingPreview": projections["timingPreview"],
        "hotspotPreview": projections["hotspotPreview"],
        "checklist": _checklist_projection(checklist),
        "artifacts": artifacts,
    }


def _checklist_projection(checklist: dict[str, Any]) -> dict[str, Any]:
    if (
        not isinstance(checklist, dict)
        or checklist.get("schema_version") != 3
        or checklist.get("kind") != "signoff_checklist"
    ):
        return {"items": []}
    items = checklist.get("checklist")
    if not isinstance(items, list):
        return {"items": []}
    if len(items) > _CHECKLIST_PROJECTION_MAX_ITEMS:
        raise EngineeringSnapshotError(
            f"Signoff checklist exceeds {_CHECKLIST_PROJECTION_MAX_ITEMS} items"
        )
    return {"items": [_checklist_item(item) for item in items if isinstance(item, dict)]}


def _checklist_item(item: dict[str, Any]) -> dict[str, Any]:
    blocked = item.get("blocked")
    return {
        "id": _text_field(item.get("id")),
        "title": _text_field(item.get("title")),
        "state": _text_field(item.get("state")),
        "blocked": blocked if isinstance(blocked, bool) else False,
        "step": _text_field(item.get("step")),
        "category": _text_field(item.get("category")),
        "summary": _text_field(item.get("summary")),
    }


def _text_field(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _snapshot_path(workspace: Any) -> Path:
    return Path(workspace.directory) / "home" / SNAPSHOT_FILENAME


def _stale_snapshot_path(workspace: Any) -> Path:
    return Path(workspace.directory) / "home" / STALE_SNAPSHOT_FILENAME


def _data_mapping(owner: Any) -> dict[str, Any]:
    data = getattr(owner, "data", {})
    return deepcopy(data) if isinstance(data, dict) else {}


def _write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    size = encoded_json_size(snapshot)
    if size > ENGINEERING_SNAPSHOT_MAX_BYTES:
        raise EngineeringSnapshotError(
            "Engineering Snapshot exceeds "
            f"{ENGINEERING_SNAPSHOT_MAX_BYTES} bytes ({size} bytes): {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    if not json_write(path, snapshot, indent=None):
        raise EngineeringSnapshotError(f"failed to persist Engineering Snapshot: {path}")


def _read_snapshot(path: Path) -> dict[str, Any]:
    try:
        snapshot = json_read_strict(path)
    except (OSError, JsonReadError) as exc:
        raise EngineeringSnapshotError(f"invalid Engineering Snapshot: {path}") from exc
    if not isinstance(snapshot, dict):
        raise EngineeringSnapshotError(f"invalid Engineering Snapshot: {path}")
    if snapshot.get("schemaVersion") != SNAPSHOT_SCHEMA_VERSION:
        raise EngineeringSnapshotError(
            f"{SNAPSHOT_REBUILD_REQUIRED}: unsupported Engineering Snapshot "
            f"schemaVersion {snapshot.get('schemaVersion')}: {path}"
        )
    if (
        not isinstance(snapshot.get("workspaceId"), str)
        or not snapshot["workspaceId"]
        or isinstance(snapshot.get("workspaceRevision"), bool)
        or not isinstance(snapshot.get("workspaceRevision"), int)
        or snapshot["workspaceRevision"] < 1
        or not validate_qor_snapshot_extension(snapshot.get("qorSnapshotExtension"))
    ):
        raise EngineeringSnapshotError(f"invalid Engineering Snapshot: {path}")
    _validate_snapshot_sections(snapshot, path.parent.parent)
    return snapshot


def _validate_snapshot_sections(snapshot: dict[str, Any], workspace_root: Path) -> None:
    for key in (
        "flow",
        "parameters",
        "checklist",
        "signoffAssessment",
        "timingPreview",
        "hotspotPreview",
    ):
        if not isinstance(snapshot.get(key), dict):
            raise EngineeringSnapshotError(f"invalid Engineering Snapshot section: {key}")
    if not isinstance(snapshot.get("metrics"), list):
        raise EngineeringSnapshotError("invalid Engineering Snapshot section: metrics")
    if "steps" in snapshot["flow"] and not isinstance(snapshot["flow"]["steps"], list):
        raise EngineeringSnapshotError("invalid Engineering Snapshot section: flow.steps")
    artifacts = snapshot.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) > SNAPSHOT_ARTIFACT_LIMIT:
        raise EngineeringSnapshotError("invalid Engineering Snapshot section: artifacts")
    workspace_root = workspace_root.resolve()
    metadata_id = _workspace_metadata_id(workspace_root)
    if metadata_id is not None and metadata_id != snapshot["workspaceId"]:
        raise EngineeringSnapshotError(
            "Engineering Snapshot workspace identity mismatch",
            code=SNAPSHOT_IDENTITY_MISMATCH,
        )
    for artifact in artifacts:
        _validate_snapshot_artifact(artifact, snapshot["workspaceId"], workspace_root)
    stale = snapshot.get("stalePredecessor")
    if stale is not None and (
        not isinstance(stale, dict)
        or type(stale.get("workspaceRevision")) is not int
        or stale["workspaceRevision"] < 1
        or not isinstance(stale.get("invalidatedStepIds"), list)
        or not all(isinstance(step_id, str) and step_id for step_id in stale["invalidatedStepIds"])
    ):
        raise EngineeringSnapshotError("invalid Engineering Snapshot stale predecessor")


def _validate_snapshot_artifact(
    artifact: object,
    workspace_id: str,
    workspace_root: Path,
) -> None:
    if not isinstance(artifact, dict):
        raise EngineeringSnapshotError("invalid Engineering Snapshot artifact")
    artifact_id = artifact.get("artifactId")
    reference = artifact.get("reference")
    availability = artifact.get("availability")
    if (
        not isinstance(artifact_id, str)
        or not isinstance(reference, str)
        or not reference
        or Path(reference).is_absolute()
        or ".." in Path(reference).parts
        or artifact_id != _artifact_id(workspace_id, reference)
        or availability not in {"missing", "available"}
    ):
        raise EngineeringSnapshotError("invalid Engineering Snapshot artifact reference")
    candidate = workspace_root / reference
    try:
        candidate.relative_to(workspace_root)
    except ValueError as exc:
        raise EngineeringSnapshotError("invalid Engineering Snapshot artifact path") from exc
    if _contains_symlink(candidate, workspace_root):
        raise EngineeringSnapshotError("invalid Engineering Snapshot artifact path")


def _contains_symlink(path: Path, root: Path) -> bool:
    current = path
    while current != root:
        if current.is_symlink() or current.parent == current:
            return True
        current = current.parent
    return root.is_symlink()


def _workspace_metadata_id(workspace_root: Path) -> str | None:
    command_path = workspace_root / "home" / "workspace-commands.json"
    try:
        payload = json_read_strict(command_path)
    except (OSError, JsonReadError):
        return None
    commands = payload.get("commands") if isinstance(payload, dict) else None
    if not isinstance(commands, dict):
        return None
    workspace_ids = {
        result.get("workspaceId")
        for command in commands.values()
        if isinstance(command, dict)
        and isinstance(result := command.get("result"), dict)
        and isinstance(result.get("workspaceId"), str)
    }
    if len(workspace_ids) > 1:
        raise EngineeringSnapshotError(
            "invalid Workspace command identity metadata", code=SNAPSHOT_IDENTITY_MISMATCH
        )
    return next(iter(workspace_ids), None)


def _artifact_id(workspace_id: str, reference: str) -> str:
    digest = hashlib.sha256(f"{workspace_id}\0{reference}".encode()).hexdigest()
    return f"artifact-{digest[:32]}"
