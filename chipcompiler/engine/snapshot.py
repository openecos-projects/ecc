import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from chipcompiler.engine.snapshot_limits import (
    CHECKLIST_INLINE_MAX_BYTES,
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

SNAPSHOT_SCHEMA_VERSION = 5
SUPPORTED_SNAPSHOT_SCHEMA_VERSIONS = frozenset({SNAPSHOT_SCHEMA_VERSION})
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
        snapshot = _read_snapshot(path)
        if snapshot["schemaVersion"] != SNAPSHOT_SCHEMA_VERSION:
            raise EngineeringSnapshotError(
                "Engineering Snapshot requires schema v5; rebuild the workspace"
            )
        return snapshot
    return create_engineering_snapshot(workspace, cause="workspace.migrated")


def read_engineering_snapshot(
    workspace: Any,
    *,
    expected_workspace_id: str | None = None,
    expected_workspace_revision: int | None = None,
    validate_artifacts: bool = False,
) -> dict[str, Any]:
    """Read the GUI projection, validating artifact contents only on explicit request.

    Workspace artifacts may be regenerated independently of this index. Consumers
    that require immutable evidence must opt in or validate the selected artifact.
    """
    snapshot = _read_snapshot(_snapshot_path(workspace), validate_artifacts=validate_artifacts)
    if expected_workspace_id is not None and snapshot["workspaceId"] != expected_workspace_id:
        raise EngineeringSnapshotError("Engineering Snapshot workspace identity mismatch")
    if (
        expected_workspace_revision is not None
        and snapshot["workspaceRevision"] != expected_workspace_revision
    ):
        raise EngineeringSnapshotError("Engineering Snapshot Workspace Revision mismatch")
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
    cause: str = "snapshot.rebuild.required",
) -> dict[str, Any]:
    raise EngineeringSnapshotError(
        "Legacy Engineering Snapshot migration is unsupported; rebuild the workspace explicitly"
    )


def commit_engineering_snapshot(
    workspace: Any,
    *,
    workspace_id: str,
    cause: str,
    changed_step: str | None = None,
    dirty_steps: list[str] | None = None,
) -> dict[str, Any]:
    current = read_engineering_snapshot(workspace, validate_artifacts=False)
    if current["schemaVersion"] != SNAPSHOT_SCHEMA_VERSION:
        raise EngineeringSnapshotError(
            "Engineering Snapshot requires schema v5; rebuild the workspace"
        )
    if current["workspaceId"] != workspace_id:
        raise EngineeringSnapshotError("Workspace identity changed before commit")
    dirty = {step for step in (dirty_steps or []) if isinstance(step, str) and step}
    if changed_step:
        dirty.add(changed_step)
    if not dirty:
        raise EngineeringSnapshotError("incremental snapshot commit requires dirty steps")
    snapshot = _build_snapshot(
        workspace,
        workspace_id=workspace_id,
        workspace_revision=current["workspaceRevision"] + 1,
        cause=cause,
        previous=current,
        dirty_steps=dirty,
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
        raise EngineeringSnapshotError(
            "Engineering Snapshot requires schema v5; rebuild the workspace"
        )
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
        previous=current,
        dirty_steps=set(invalidated),
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
    previous: dict[str, Any] | None = None,
    dirty_steps: set[str] | None = None,
) -> dict[str, Any]:
    flow_owner = getattr(workspace, "flow", None)
    flow = _data_mapping(flow_owner)
    if not flow and flow_owner is not None:
        steps = flow_owner.steps()
        flow = {"steps": deepcopy(steps)} if steps else {}
    home = _data_mapping(getattr(workspace, "home", None))
    checklist_path = home.get("checklist") or (
        Path(workspace.directory) / "home" / "checklist.json"
    )
    checklist_result = read_bounded_json_object(
        Path(checklist_path),
        CHECKLIST_INLINE_MAX_BYTES,
    )
    checklist = checklist_result.data if checklist_result.status == "available" else {}
    from chipcompiler.engine.analysis import build_workspace_analysis
    from chipcompiler.engine.signoff_assessment import build_signoff_assessment

    analysis, artifacts, metrics_by_step, summary_status_by_step = build_workspace_analysis(
        workspace,
        workspace_id,
        step_ids=dirty_steps,
        inline=False,
    )
    if previous is not None:
        analysis, artifacts, metrics_by_step, summary_status_by_step = _merge_incremental_analysis(
            previous,
            analysis,
            artifacts,
            metrics_by_step,
            summary_status_by_step,
            dirty_steps or set(),
        )
    for step in analysis.get("steps", []):
        if isinstance(step, dict) and isinstance(step.get("stepId"), str):
            step["metricCount"] = len(metrics_by_step.get(step["stepId"], []))
            step["summaryStatus"] = summary_status_by_step.get(step["stepId"], "unavailable")
    if previous is not None and not _flow_is_terminal(flow):
        qor_extension = unavailable_qor_snapshot_extension("incremental analysis pending")
    else:
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
        "metrics": _flatten_metrics(analysis, metrics_by_step),
        "qorSnapshotExtension": qor_extension,
        "signoffAssessment": build_signoff_assessment(workspace, checklist=checklist),
        "artifacts": artifacts,
    }


def _snapshot_path(workspace: Any) -> Path:
    return Path(workspace.directory) / "home" / SNAPSHOT_FILENAME


def _stale_snapshot_path(workspace: Any) -> Path:
    return Path(workspace.directory) / "home" / STALE_SNAPSHOT_FILENAME


def _data_mapping(owner: Any) -> dict[str, Any]:
    data = getattr(owner, "data", {})
    return deepcopy(data) if isinstance(data, dict) else {}


def _flow_is_terminal(flow: dict[str, Any]) -> bool:
    steps = flow.get("steps")
    return (
        isinstance(steps, list)
        and bool(steps)
        and all(
            isinstance(step, dict) and step.get("state") in {"Success", "Skipped"}
            for step in steps
        )
    )


def _merge_incremental_analysis(
    previous: dict[str, Any],
    changed_analysis: dict[str, Any],
    changed_artifacts: list[dict[str, Any]],
    changed_metrics: dict[str, list[dict[str, Any]]],
    changed_summary_status: dict[str, str],
    dirty_steps: set[str],
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[str, str],
]:
    previous_analysis = previous.get("analysis")
    previous_steps = (
        previous_analysis.get("steps", []) if isinstance(previous_analysis, dict) else []
    )
    changed_by_id = {
        step.get("stepId"): step
        for step in changed_analysis.get("steps", [])
        if isinstance(step, dict) and isinstance(step.get("stepId"), str)
    }
    merged_steps = [
        changed_by_id.get(step.get("stepId"), step)
        for step in previous_steps
        if isinstance(step, dict)
    ]
    known_ids = {step.get("stepId") for step in merged_steps if isinstance(step, dict)}
    merged_steps.extend(
        step for step in changed_by_id.values() if step.get("stepId") not in known_ids
    )
    merged_steps.sort(key=lambda step: int(step.get("order", 0)))

    previous_artifacts = previous.get("artifacts")
    previous_artifacts = previous_artifacts if isinstance(previous_artifacts, list) else []
    merged_artifacts = [
        artifact
        for artifact in previous_artifacts
        if not isinstance(artifact, dict) or artifact.get("stepId") not in dirty_steps
    ]
    merged_artifacts.extend(changed_artifacts)

    metrics_by_step = _metrics_by_step(previous)
    metrics_by_step.update({step_id: [] for step_id in dirty_steps})
    metrics_by_step.update(changed_metrics)
    summary_status = _summary_status_by_step(previous)
    summary_status.update({step_id: "unavailable" for step_id in dirty_steps})
    summary_status.update(changed_summary_status)
    return {"steps": merged_steps}, merged_artifacts, metrics_by_step, summary_status


def _metrics_by_step(snapshot: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    metrics = snapshot.get("metrics")
    if not isinstance(metrics, list):
        raise EngineeringSnapshotError("Engineering Snapshot comparison projection is unavailable")
    result: dict[str, list[dict[str, Any]]] = {}
    for metric in metrics:
        if not isinstance(metric, dict) or not isinstance(metric.get("stepId"), str):
            raise EngineeringSnapshotError("Engineering Snapshot comparison projection is invalid")
        result.setdefault(metric["stepId"], []).append(metric)
    return result


def _summary_status_by_step(snapshot: dict[str, Any]) -> dict[str, str]:
    analysis = snapshot.get("analysis")
    steps = analysis.get("steps") if isinstance(analysis, dict) else None
    if not isinstance(steps, list):
        raise EngineeringSnapshotError("Engineering Snapshot QoR summary is unavailable")
    result: dict[str, str] = {}
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("stepId"), str):
            continue
        summary = step.get("summary")
        existing = step.get("summaryStatus")
        data = summary.get("data") if isinstance(summary, dict) else None
        status = data.get("quality_status") if isinstance(data, dict) else None
        if not isinstance(status, str) or not status:
            status = existing
        result[step["stepId"]] = (
            str(status) if isinstance(status, str) and status else "unavailable"
        )
    return result


def _flatten_metrics(
    analysis: dict[str, Any], metrics_by_step: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    steps = analysis.get("steps", [])
    return [
        {**metric, "stepId": str(step.get("stepId"))}
        for step in steps
        if isinstance(step, dict)
        for metric in metrics_by_step.get(str(step.get("stepId")), [])
    ]


def _write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    size = encoded_json_size(snapshot)
    if size > ENGINEERING_SNAPSHOT_MAX_BYTES:
        raise EngineeringSnapshotError(
            "Engineering Snapshot exceeds "
            f"{ENGINEERING_SNAPSHOT_MAX_BYTES} bytes ({size} bytes): {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    if not json_write(path, snapshot):
        raise EngineeringSnapshotError(f"failed to persist Engineering Snapshot: {path}")


def _read_snapshot(path: Path, *, validate_artifacts: bool = False) -> dict[str, Any]:
    try:
        size = path.stat().st_size
        if size > ENGINEERING_SNAPSHOT_MAX_BYTES:
            raise EngineeringSnapshotError(
                "Engineering Snapshot exceeds "
                f"{ENGINEERING_SNAPSHOT_MAX_BYTES} bytes ({size} bytes): {path}"
            )
        snapshot = json_read_strict(path)
    except EngineeringSnapshotError:
        raise
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
        or "qorAssessment" in snapshot
        or not validate_qor_snapshot_extension(snapshot.get("qorSnapshotExtension"))
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
    for key in (
        "flow",
        "parameters",
        "checklist",
        "analysis",
        "signoffAssessment",
    ):
        if not isinstance(snapshot.get(key), dict):
            raise EngineeringSnapshotError(f"invalid Engineering Snapshot section: {key}")
    if "steps" in snapshot["flow"] and not isinstance(snapshot["flow"]["steps"], list):
        raise EngineeringSnapshotError("invalid Engineering Snapshot section: flow.steps")
    if "steps" in snapshot["analysis"] and not isinstance(snapshot["analysis"]["steps"], list):
        raise EngineeringSnapshotError("invalid Engineering Snapshot section: analysis.steps")
    artifacts = snapshot.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) > 4096:
        raise EngineeringSnapshotError("invalid Engineering Snapshot section: artifacts")
    metrics = snapshot.get("metrics")
    if not isinstance(metrics, list) or not all(
        isinstance(metric, dict) and isinstance(metric.get("stepId"), str) and metric["stepId"]
        for metric in metrics
    ):
        raise EngineeringSnapshotError("invalid Engineering Snapshot metrics")
    metric_counts: dict[str, int] = {}
    for metric in metrics:
        metric_counts[metric["stepId"]] = metric_counts.get(metric["stepId"], 0) + 1
    step_ids: set[str] = set()
    for step in snapshot["analysis"].get("steps", []):
        if not isinstance(step, dict) or not isinstance(step.get("stepId"), str):
            raise EngineeringSnapshotError("invalid Engineering Snapshot analysis step")
        if step["stepId"] in step_ids:
            raise EngineeringSnapshotError("duplicate Engineering Snapshot analysis step")
        step_ids.add(step["stepId"])
        if type(step.get("metricCount")) is not int or step["metricCount"] < 0:
            raise EngineeringSnapshotError("invalid Engineering Snapshot analysis metric count")
        if step["metricCount"] != metric_counts.get(step["stepId"], 0):
            raise EngineeringSnapshotError("invalid Engineering Snapshot analysis metric count")
        if not isinstance(step.get("summaryStatus"), str) or not step["summaryStatus"]:
            raise EngineeringSnapshotError("invalid Engineering Snapshot analysis summary status")
    if any(metric["stepId"] not in step_ids for metric in metrics):
        raise EngineeringSnapshotError("orphan Engineering Snapshot metric")
    workspace_root = workspace_root.resolve()
    metadata_id = _workspace_metadata_id(workspace_root)
    if metadata_id is not None and metadata_id != snapshot["workspaceId"]:
        raise EngineeringSnapshotError("Engineering Snapshot workspace identity mismatch")
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
    integrity = artifact.get("integrity")
    if (
        not isinstance(artifact_id, str)
        or not isinstance(reference, str)
        or not reference
        or Path(reference).is_absolute()
        or ".." in Path(reference).parts
        or artifact_id != _artifact_id(workspace_id, reference)
        or availability not in {"missing", "available"}
        or integrity not in {"verified", "mismatched", "unverified", "unsafe", "not_checked"}
    ):
        raise EngineeringSnapshotError("invalid Engineering Snapshot artifact reference")
    if availability != "available":
        return
    candidate = workspace_root / reference
    try:
        candidate.relative_to(workspace_root)
    except ValueError as exc:
        raise EngineeringSnapshotError("invalid Engineering Snapshot artifact path") from exc
    if _contains_symlink(candidate, workspace_root):
        raise EngineeringSnapshotError("invalid Engineering Snapshot artifact path")
    if integrity != "verified" or not validate_artifacts:
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
        raise EngineeringSnapshotError("invalid Workspace command identity metadata")
    return next(iter(workspace_ids), None)


def _artifact_id(workspace_id: str, reference: str) -> str:
    digest = hashlib.sha256(f"{workspace_id}\0{reference}".encode()).hexdigest()
    return f"artifact-{digest[:32]}"
