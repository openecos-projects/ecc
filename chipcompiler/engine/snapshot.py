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
from chipcompiler.utility import JsonReadError, file_digest, json_read_strict, json_write

LEGACY_SNAPSHOT_SCHEMA_VERSION = 2
SNAPSHOT_V3_SCHEMA_VERSION = 3
SNAPSHOT_SCHEMA_VERSION = 4
SUPPORTED_SNAPSHOT_SCHEMA_VERSIONS = frozenset(
    {LEGACY_SNAPSHOT_SCHEMA_VERSION, SNAPSHOT_V3_SCHEMA_VERSION, SNAPSHOT_SCHEMA_VERSION}
)
SNAPSHOT_FILENAME = "engineering-snapshot.json"
STALE_SNAPSHOT_FILENAME = "engineering-snapshot.stale.json"
SNAPSHOT_MIGRATION_CAUSE = "snapshot.migrated.to_v4"
SNAPSHOT_REBUILD_REQUIRED = "snapshot_rebuild_required"
SNAPSHOT_IDENTITY_MISMATCH = "snapshot_identity_mismatch"
SNAPSHOT_REVISION_MISMATCH = "snapshot_revision_mismatch"
SNAPSHOT_ARTIFACT_LIMIT = 4096


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
    workspace_spec: object | None = None,
) -> dict[str, Any]:
    snapshot = _build_snapshot(
        workspace,
        workspace_id=workspace_id or f"workspace-{uuid4().hex}",
        workspace_revision=workspace_revision,
        cause=cause,
        workspace_spec=workspace_spec,
    )
    _write_snapshot(_snapshot_path(workspace), snapshot)
    return snapshot


def ensure_engineering_snapshot(workspace: Any) -> dict[str, Any]:
    path = _snapshot_path(workspace)
    if path.is_file():
        snapshot = _read_snapshot(path)
        if snapshot["schemaVersion"] != SNAPSHOT_SCHEMA_VERSION:
            raise EngineeringSnapshotError("Engineering Snapshot requires schemaVersion 4")
        return snapshot
    return create_engineering_snapshot(workspace, cause="workspace.migrated")


def open_workspace_snapshot(workspace: Any) -> dict[str, Any]:
    """Open-time compatibility alias used by the workspace configuration API."""
    return ensure_engineering_snapshot(workspace)


def read_engineering_snapshot(
    workspace: Any,
    *,
    expected_workspace_id: str | None = None,
    expected_workspace_revision: int | None = None,
    validate_artifacts: bool = False,
) -> dict[str, Any]:
    """Read the committed Snapshot projection.

    Artifacts are path references into the workspace, never versioned copies;
    readers get path-safety validation but no content fingerprinting.
    """
    snapshot = _read_snapshot(
        _snapshot_path(workspace),
        validate_artifacts=validate_artifacts,
    )
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
    return _read_snapshot(path, validate_artifacts=False) if path.is_file() else None


def migrate_engineering_snapshot(
    workspace: Any,
    *,
    expected_workspace_revision: int | None = None,
    cause: str = SNAPSHOT_MIGRATION_CAUSE,
) -> dict[str, Any]:
    """Rebuild one legacy v2/v3 Snapshot into the production v4 contract."""
    current = _read_snapshot(_snapshot_path(workspace))
    if current["schemaVersion"] not in {
        LEGACY_SNAPSHOT_SCHEMA_VERSION,
        SNAPSHOT_V3_SCHEMA_VERSION,
    }:
        raise EngineeringSnapshotError("Snapshot migration requires schemaVersion 2 or 3")
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
            workspace_revision=current["workspaceRevision"],
            cause=cause,
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


# Kept until downstream callers migrate to the version-neutral entry point.
migrate_engineering_snapshot_v2_to_v3 = migrate_engineering_snapshot


def commit_engineering_snapshot(
    workspace: Any,
    *,
    workspace_id: str,
    cause: str,
) -> dict[str, Any]:
    current = read_engineering_snapshot(workspace, validate_artifacts=False)
    if current["schemaVersion"] != SNAPSHOT_SCHEMA_VERSION:
        raise EngineeringSnapshotError("Engineering Snapshot requires schemaVersion 4")
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
    current = read_engineering_snapshot(workspace, validate_artifacts=False)
    if current["schemaVersion"] != SNAPSHOT_SCHEMA_VERSION:
        raise EngineeringSnapshotError("Engineering Snapshot requires schemaVersion 4")
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
    workspace_spec: object | None = None,
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
        if strict_qor:
            raise
        qor_extension = unavailable_qor_snapshot_extension(str(exc))
    snapshot = {
        "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "workspaceId": workspace_id,
        "workspaceRevision": workspace_revision,
        "cause": cause,
        "flow": flow,
        "parameters": _data_mapping(getattr(workspace, "parameters", None)),
        # Keep the v4 compatibility envelope used by the CLI workspace
        # migration path while exposing the bounded v6 projections below.
        "analysis": {"steps": deepcopy(flow.get("steps", []))},
        "qorAssessment": {"metrics": deepcopy(projections["metrics"])},
        "metrics": projections["metrics"],
        "qorSnapshotExtension": qor_extension,
        "signoffAssessment": build_signoff_assessment(workspace, checklist=checklist),
        "timingPreview": projections["timingPreview"],
        "hotspotPreview": projections["hotspotPreview"],
        "checklist": _checklist_projection(checklist),
        "artifacts": artifacts,
    }
    if schema_version != SNAPSHOT_SCHEMA_VERSION:
        snapshot["schemaVersion"] = schema_version
    from chipcompiler.engine.step_outputs import resolve_workspace_step_outputs
    from chipcompiler.engine.workspace_configuration import (
        build_workspace_configuration_projection,
    )

    try:
        projection = build_workspace_configuration_projection(workspace)
    except (AttributeError, KeyError, TypeError, ValueError, OSError, JsonReadError):
        projection = _minimal_workspace_projection(workspace)
    if isinstance(workspace_spec, dict):
        projection["workspaceSpec"] = deepcopy(workspace_spec)
    snapshot.update(projection)
    snapshot["stepOutputs"] = resolve_workspace_step_outputs(workspace)
    return snapshot


def _minimal_workspace_projection(workspace: Any) -> dict[str, Any]:
    design = getattr(workspace, "design", None)
    flow = getattr(workspace, "flow", None)
    flow_data = getattr(flow, "data", {})
    steps = flow_data.get("steps", []) if isinstance(flow_data, dict) else []
    names = [str(step.get("name")) for step in steps if isinstance(step, dict) and step.get("name")]
    return {
        "workspaceSpec": {
            "schemaVersion": 1,
            "design": {
                "name": str(getattr(design, "name", "")),
                "topModule": str(getattr(design, "top_module", "")),
                "clockPort": "",
            },
            "inputMode": "rtl",
            "inputs": [],
            "pdk": {"familyId": "", "version": "", "mode": "default"},
            "flow": {
                "flowId": "custom",
                **({"fromStepId": names[0], "throughStepId": names[-1]} if names else {}),
            },
            "parameters": {},
        },
        "workspaceBindings": {"inputs": {}, "pdk": {"root": "", "version": ""}},
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
    if len(items) > 512:
        raise EngineeringSnapshotError("Signoff checklist exceeds 512 items")
    return {"items": [_checklist_item(item) for item in items if isinstance(item, dict)]}


def _checklist_item(item: dict[str, Any]) -> dict[str, Any]:
    blocked = item.get("blocked")
    return {
        "id": item.get("id") if isinstance(item.get("id"), str) else "",
        "title": item.get("title") if isinstance(item.get("title"), str) else "",
        "state": item.get("state") if isinstance(item.get("state"), str) else "",
        "blocked": blocked if isinstance(blocked, bool) else False,
        "step": item.get("step") if isinstance(item.get("step"), str) else "",
        "category": item.get("category") if isinstance(item.get("category"), str) else "",
        "summary": item.get("summary") if isinstance(item.get("summary"), str) else "",
    }


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


def _read_snapshot(path: Path, *, validate_artifacts: bool = False) -> dict[str, Any]:
    try:
        snapshot = json_read_strict(path)
    except (OSError, JsonReadError) as exc:
        raise EngineeringSnapshotError(f"invalid Engineering Snapshot: {path}") from exc
    if not isinstance(snapshot, dict):
        raise EngineeringSnapshotError(f"invalid Engineering Snapshot: {path}")
    schema_version = snapshot.get("schemaVersion")
    if schema_version not in SUPPORTED_SNAPSHOT_SCHEMA_VERSIONS:
        raise EngineeringSnapshotError(
            f"invalid Engineering Snapshot: {SNAPSHOT_REBUILD_REQUIRED}: unsupported "
            "Engineering Snapshot "
            f"schemaVersion {schema_version}: {path}"
        )
    if (
        not isinstance(snapshot.get("workspaceId"), str)
        or not snapshot["workspaceId"]
        or isinstance(snapshot.get("workspaceRevision"), bool)
        or not isinstance(snapshot.get("workspaceRevision"), int)
        or snapshot["workspaceRevision"] < 1
        or (
            schema_version in {SNAPSHOT_V3_SCHEMA_VERSION, SNAPSHOT_SCHEMA_VERSION}
            and not validate_qor_snapshot_extension(snapshot.get("qorSnapshotExtension"))
        )
    ):
        raise EngineeringSnapshotError(f"invalid Engineering Snapshot: {path}")
    _validate_snapshot_sections(
        snapshot,
        path.parent.parent,
        validate_artifacts=validate_artifacts,
    )
    return snapshot


def _validate_snapshot_sections(
    snapshot: dict[str, Any],
    workspace_root: Path,
    *,
    validate_artifacts: bool,
) -> None:
    required = ["flow", "parameters", "checklist", "signoffAssessment"]
    if snapshot["schemaVersion"] == SNAPSHOT_SCHEMA_VERSION:
        required.extend(("timingPreview", "hotspotPreview"))
    else:
        required.extend(("analysis", "qorAssessment"))
    for key in required:
        if not isinstance(snapshot.get(key), dict):
            raise EngineeringSnapshotError(f"invalid Engineering Snapshot section: {key}")
    if snapshot["schemaVersion"] == SNAPSHOT_SCHEMA_VERSION:
        for key in ("workspaceSpec", "workspaceBindings", "stepOutputs"):
            if not isinstance(snapshot.get(key), dict):
                raise EngineeringSnapshotError(f"invalid Engineering Snapshot section: {key}")
        _validate_step_outputs(snapshot, workspace_root)
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
        _validate_snapshot_artifact(
            artifact,
            snapshot["workspaceId"],
            workspace_root,
            validate_artifacts=validate_artifacts,
        )
    stale = snapshot.get("stalePredecessor")
    if stale is not None and (
        not isinstance(stale, dict)
        or type(stale.get("workspaceRevision")) is not int
        or stale["workspaceRevision"] < 1
        or not isinstance(stale.get("invalidatedStepIds"), list)
        or not all(isinstance(step_id, str) and step_id for step_id in stale["invalidatedStepIds"])
    ):
        raise EngineeringSnapshotError("invalid Engineering Snapshot stale predecessor")


def _validate_step_outputs(snapshot: dict[str, Any], workspace_root: Path) -> None:
    step_outputs = snapshot["stepOutputs"]
    if (
        step_outputs.get("directory") != "."
        or not isinstance(step_outputs.get("design"), str)
        or not isinstance(step_outputs.get("steps"), list)
    ):
        raise EngineeringSnapshotError("invalid Engineering Snapshot section: stepOutputs")
    steps = step_outputs["steps"]
    if len(steps) > 4096:
        raise EngineeringSnapshotError("invalid Engineering Snapshot section: stepOutputs")
    references = 0
    for artifact in (step_outputs.get("sdc"),):
        if artifact is not None:
            references += 1
            _validate_step_output_artifact(artifact, snapshot, workspace_root)
    for step in steps:
        if (
            not isinstance(step, dict)
            or not isinstance(step.get("step"), str)
            or not step["step"]
            or not isinstance(step.get("tool"), str)
            or not isinstance(step.get("state"), str)
        ):
            raise EngineeringSnapshotError("invalid Engineering Snapshot step output")
        for key in ("verilog", "def"):
            artifact = step.get(key)
            if artifact is not None:
                references += 1
                _validate_step_output_artifact(artifact, snapshot, workspace_root)
    if references > 4096:
        raise EngineeringSnapshotError("invalid Engineering Snapshot section: stepOutputs")


def _validate_step_output_artifact(
    artifact: object,
    snapshot: dict[str, Any],
    workspace_root: Path,
) -> None:
    if (
        not isinstance(artifact, dict)
        or not isinstance(artifact.get("path"), str)
        or not artifact["path"]
        or type(artifact.get("exists")) is not bool
    ):
        raise EngineeringSnapshotError("invalid Engineering Snapshot step output artifact")
    reference = Path(artifact["path"])
    if not reference.is_absolute():
        if ".." in reference.parts:
            raise EngineeringSnapshotError("invalid Engineering Snapshot step output path")
        return
    candidate = reference.resolve(strict=False)
    bindings = snapshot["workspaceBindings"]
    authorized_files: set[Path] = set()
    authorized_roots: set[Path] = set()
    inputs = bindings.get("inputs", {})
    if isinstance(inputs, dict):
        authorized_files.update(
            Path(value).expanduser().resolve(strict=False)
            for value in inputs.values()
            if isinstance(value, str) and value
        )
    pdk = bindings.get("pdk", {})
    if isinstance(pdk, dict):
        root = pdk.get("root")
        if isinstance(root, str) and root:
            authorized_roots.add(Path(root).expanduser().resolve(strict=False))
        files = pdk.get("files", {})
        if isinstance(files, dict):
            authorized_files.update(
                Path(value).expanduser().resolve(strict=False)
                for value in files.values()
                if isinstance(value, str) and value
            )
    if candidate in authorized_files:
        return
    for root in authorized_roots:
        try:
            candidate.relative_to(root)
            return
        except ValueError:
            continue
    raise EngineeringSnapshotError("invalid Engineering Snapshot step output path")


def _validate_snapshot_artifact(
    artifact: object,
    workspace_id: str,
    workspace_root: Path,
    *,
    validate_artifacts: bool,
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
        or availability not in {"missing", "available", "stale"}
    ):
        raise EngineeringSnapshotError("invalid Engineering Snapshot artifact reference")
    if availability != "available" or not validate_artifacts:
        return
    digest = artifact.get("sha256")
    size = artifact.get("sizeBytes")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest.lower())
        or type(size) is not int
        or size < 0
    ):
        raise EngineeringSnapshotError("invalid Engineering Snapshot artifact fingerprint")
    candidate = workspace_root / reference
    try:
        candidate.relative_to(workspace_root)
    except ValueError as exc:
        raise EngineeringSnapshotError("invalid Engineering Snapshot artifact path") from exc
    if _contains_symlink(candidate, workspace_root):
        raise EngineeringSnapshotError("invalid Engineering Snapshot artifact path")
    if file_digest(candidate) != (digest, size):
        raise EngineeringSnapshotError(
            f"Engineering Snapshot artifact fingerprint mismatch: {reference}"
        )


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
