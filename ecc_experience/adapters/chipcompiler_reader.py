import hashlib
from contextlib import suppress
from pathlib import Path

from pydantic import ValidationError

from chipcompiler.engine.snapshot import (
    SNAPSHOT_FILENAME,
    EngineeringSnapshotError,
    read_engineering_snapshot_from_directory,
)
from chipcompiler.utility.workspace_lock import workspace_lock
from ecc_experience.files import (
    SMALL_EVIDENCE_LIMIT,
    canonical_bytes,
    digest,
    file_digest,
    read_json,
    safe_child,
)
from ecc_experience.models import (
    Evidence,
    ExperienceError,
    InputDigest,
    SourceObservation,
    WorkspaceObservation,
)


def _capture(
    root: Path, reference: str, availability: str, *, validate_json: bool = True
) -> tuple[Evidence, bytes | None]:
    path = safe_child(root, reference)
    if availability == "stale":
        return Evidence(reference=reference, status="stale"), None
    if not path.is_file():
        status = "stale" if availability == "available" else "missing"
        return Evidence(reference=reference, status=status, reason="File is absent"), None
    checksum, size = file_digest(path)
    content = None
    stored_path = None
    status = "available"
    reason = None
    if path.suffix in {".json", ".toml"} and size <= SMALL_EVIDENCE_LIMIT:
        with path.open("rb") as stream:
            content = stream.read(SMALL_EVIDENCE_LIMIT + 1)
        if hashlib.sha256(content).hexdigest() != checksum:
            raise ExperienceError(
                "Evidence changed during capture", code="experience_source_changed"
            )
        if path.suffix == ".json" and validate_json:
            try:
                read_json(path, SMALL_EVIDENCE_LIMIT)
            except ExperienceError as exc:
                status, reason = "invalid", str(exc)
        stored_path = f"evidence/{checksum}{path.suffix}"
    return Evidence(
        reference=reference,
        status=status,
        sha256=checksum,
        bytes=size,
        stored_path=stored_path,
        reason=reason,
    ), content


def _input_digests(facts: dict) -> list[InputDigest]:
    specification = facts.get("workspaceSpec", {})
    binding_data = facts.get("workspaceBindings", {})
    if not isinstance(specification, dict) or not isinstance(binding_data, dict):
        raise ExperienceError("Invalid workspace specification or bindings")
    bindings = binding_data.get("inputs", {})
    declarations = specification.get("inputs", [])
    if not isinstance(bindings, dict) or not isinstance(declarations, list):
        raise ExperienceError("Invalid workspace input bindings")
    roles = {
        item.get("inputId"): item.get("role", "unknown")
        for item in declarations
        if isinstance(item, dict)
    }
    inputs = []
    for input_id, reference in sorted(bindings.items()):
        if not isinstance(input_id, str) or not isinstance(roles.get(input_id, "unknown"), str):
            raise ExperienceError("Invalid input identity or role")
        checksum = None
        if isinstance(reference, str) and Path(reference).is_absolute():
            with suppress(OSError):
                checksum, _ = file_digest(Path(reference))
        inputs.append(
            InputDigest(
                input_id=input_id,
                role=roles.get(input_id, "unknown"),
                status="available" if checksum is not None else "unavailable",
                sha256=checksum,
            )
        )
    return inputs


def _read_locked(root: Path) -> WorkspaceObservation:
    snapshot_path = safe_child(root, f"home/{SNAPSHOT_FILENAME}")
    limitations = [
        "No stable execution attempt ID; observations are not independent execution samples",
        "Artifact digests are captured at collection, not bound to the original commit",
        "Input closure, includes and PDK contents are not verified; fingerprints are partial",
        "Configured parameters do not prove tool consumption",
        "Legacy memory values retain their original scope; no new resource measurement is inferred",
    ]
    if snapshot_path.exists():
        try:
            facts = read_engineering_snapshot_from_directory(root)
        except EngineeringSnapshotError as exc:
            raise ExperienceError(str(exc), code="experience_snapshot_invalid") from exc
        source = SourceObservation(
            workspace_root=str(root),
            workspace_id=facts["workspaceId"],
            workspace_revision=facts["workspaceRevision"],
            snapshot_schema=facts["schemaVersion"],
            snapshot_digest=digest(facts),
            cause=facts.get("cause"),
            observation_type="committed_import",
        )
    else:
        flow_path = safe_child(root, "home/flow.json")
        if not flow_path.is_file():
            raise ExperienceError("Workspace has neither a snapshot nor a legacy flow")
        facts = {"flow": read_json(flow_path)}
        source = SourceObservation(
            workspace_root=str(root),
            workspace_id=None,
            snapshot_schema=None,
            snapshot_digest=None,
            cause=None,
            observation_type="legacy_import",
        )
        limitations.append("Legacy import is read-only; no snapshot was created or migrated")
    steps = facts.get("flow", {}).get("steps", [])
    if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
        raise ExperienceError("Invalid flow steps")
    if any(str(step.get("state", "")).casefold() in {"ongoing", "pending"} for step in steps):
        raise ExperienceError("Workspace flow is still active", code="experience_workspace_busy")

    references = {
        "home/flow.json": "available",
        "home/checklist.json": "missing",
        "home/params.toml": "missing",
    }
    opaque_reports = set()
    for artifact in facts.get("artifacts", []):
        references[artifact["reference"]] = artifact["availability"]
        if artifact.get("kind") == "report_text":
            opaque_reports.add(artifact["reference"])
    step_outputs = facts.get("stepOutputs", {})
    output_refs = [step_outputs.get("sdc")]
    for step in step_outputs.get("steps", []):
        output_refs.extend(step.get(key) for key in ("verilog", "def"))
    for output in output_refs:
        if not isinstance(output, dict):
            continue
        reference = output.get("path")
        if not isinstance(reference, str) or Path(reference).is_absolute():
            continue
        references[reference] = "available" if output.get("exists") else "missing"
    evidence = []
    copies = {}
    if snapshot_path.exists():
        content = snapshot_path.read_bytes()
        if canonical_bytes(read_json(snapshot_path)) != canonical_bytes(facts):
            raise ExperienceError(
                "Snapshot changed during capture", code="experience_source_changed"
            )
        checksum = hashlib.sha256(content).hexdigest()
        stored_path = f"evidence/{checksum}.json"
        evidence.append(
            Evidence(
                reference=f"home/{SNAPSHOT_FILENAME}",
                status="available",
                sha256=checksum,
                bytes=len(content),
                stored_path=stored_path,
            )
        )
        copies[stored_path] = content
    for reference, availability in sorted(references.items()):
        record, content = _capture(
            root, reference, availability, validate_json=reference not in opaque_reports
        )
        evidence.append(record)
        if record.stored_path is not None and content is not None:
            copies[record.stored_path] = content
    flow_path = safe_child(root, "home/flow.json")
    if flow_path.exists() and read_json(flow_path) != facts["flow"]:
        raise ExperienceError(
            "Flow does not match committed snapshot", code="experience_source_changed"
        )
    for record in evidence:
        if (
            record.sha256 is not None
            and record.bytes is not None
            and file_digest(safe_child(root, record.reference)) != (record.sha256, record.bytes)
        ):
            raise ExperienceError(
                "Evidence changed during capture", code="experience_source_changed"
            )
    if (
        snapshot_path.exists()
        and digest(read_engineering_snapshot_from_directory(root)) != source.snapshot_digest
    ):
        raise ExperienceError(
            "Snapshot revision changed during capture", code="experience_source_changed"
        )
    return WorkspaceObservation(source, facts, _input_digests(facts), evidence, copies, limitations)


def read_workspace_observation(directory: str | Path) -> WorkspaceObservation:
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise ExperienceError("Workspace does not exist")
    try:
        with workspace_lock(root, blocking=False):
            return _read_locked(root)
    except BlockingIOError as exc:
        raise ExperienceError("Workspace lock is busy", code="experience_workspace_busy") from exc
    except (TypeError, KeyError, AttributeError, ValidationError) as exc:
        raise ExperienceError("Malformed workspace evidence") from exc
