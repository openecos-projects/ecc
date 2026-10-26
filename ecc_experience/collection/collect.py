from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from ecc_experience import __version__
from ecc_experience.adapters.input_closure import content_fingerprint
from ecc_experience.files import case_identity, digest
from ecc_experience.knowledge.design_tags import design_tags, memory_identity
from ecc_experience.knowledge.failure import classify_failure
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.models import (
    ConstraintIdentity,
    DesignIdentity,
    ExperienceCase,
    ExperienceError,
    ProcessIdentity,
    ToolchainIdentity,
    WorkspaceObservation,
)


class ObservationReader(Protocol):
    def __call__(self, directory: str | Path) -> WorkspaceObservation: ...


@dataclass(frozen=True)
class CollectionResult:
    case: ExperienceCase
    status: str


def collect_committed_case(
    directory: str | Path,
    store: ExperienceStore,
    reader: ObservationReader,
    *,
    attempt_id: str | None = None,
    expected_snapshot_digest: str | None = None,
    execution_context: dict | None = None,
    parameter_evidence: dict | None = None,
) -> CollectionResult:
    workspace = Path(directory).expanduser().resolve()
    if store.root.is_relative_to(workspace) or workspace.is_relative_to(store.root):
        raise ExperienceError("Store and source workspace must not overlap")
    observation = reader(workspace)
    if expected_snapshot_digest is not None:
        actual_digest = observation.source.snapshot_digest
        if actual_digest != expected_snapshot_digest:
            raise ExperienceError(
                "Workspace revision changed before experience drain",
                code="experience_source_changed",
            )
    if attempt_id is not None:
        observation = WorkspaceObservation(
            source=observation.source.model_copy(update={"attempt_id": attempt_id}),
            facts=observation.facts,
            inputs=observation.inputs,
            evidence=observation.evidence,
            copies=observation.copies,
            limitations=observation.limitations,
            design=observation.design,
            constraints=observation.constraints,
            parameter_evidence=observation.parameter_evidence,
        )
    spec = observation.facts.get("workspaceSpec", {})
    fingerprint = content_fingerprint(observation.facts, observation.inputs)
    facts = observation.facts
    process_fingerprint = None
    process = None
    toolchain = ToolchainIdentity()
    if execution_context is not None:
        if (
            execution_context.get("schema") != "ecc-experience-execution-context/1"
            or attempt_id is None
            or execution_context.get("attempt_id") != attempt_id
        ):
            raise ExperienceError("Execution context is not bound to this attempt")
        facts = {**facts, "experienceExecutionContext": execution_context}
        process = execution_context.get("process", {})
        if isinstance(process, dict) and process.get("status") == "available":
            process_fingerprint = process.get("fingerprint")
        runtime = execution_context.get("runtime")
        if isinstance(runtime, dict):
            toolchain = ToolchainIdentity(
                runtime_fingerprint=digest(runtime),
                status="available",
                sources=runtime.get("sources", {})
                if isinstance(runtime.get("sources"), dict)
                else {},
                tools=runtime.get("tools", {}) if isinstance(runtime.get("tools"), dict) else {},
                native_packages=runtime.get("native_packages", {})
                if isinstance(runtime.get("native_packages"), dict)
                else {},
            )
    process_identity = _process_identity(process)
    design_data = observation.design or {}
    design_memory = memory_identity(facts)
    design = DesignIdentity(
        fingerprint=design_data.get("fingerprint"),
        top_module=design_data.get("top_module"),
        tags=design_tags(facts),
        closure=design_data.get("closure", "unknown"),
        **design_memory,
    )
    constraints = ConstraintIdentity(**(observation.constraints or {}))
    parameter_evidence = (
        parameter_evidence
        or observation.parameter_evidence
        or {
            "level": "configured"
            if isinstance(spec, dict) and spec.get("parameters")
            else "unknown",
            "receipt_status": "not_applicable",
        }
    )
    case = ExperienceCase(
        schema_version=2,
        case_id="",
        collector_version=__version__,
        collected_at=datetime.now(UTC).isoformat(),
        source=observation.source,
        input_content_fingerprint=fingerprint,
        inputs=observation.inputs,
        facts=facts,
        design_fingerprint=design.fingerprint,
        process_fingerprint=process_fingerprint,
        design=design,
        constraints=constraints,
        process=process_identity,
        toolchain=toolchain,
        evidence=observation.evidence,
        limitations=observation.limitations,
        parameter_evidence=parameter_evidence,
        failure=classify_failure(facts),
        validation_scope="committed_observation"
        if observation.source.observation_type == "committed_import"
        else "legacy_import",
    )
    case = case.model_copy(update={"case_id": case_identity(case.model_dump())})
    status = store.put(case, observation.copies)
    return CollectionResult(case=store.read(case.case_id), status=status)


def _process_identity(value: object) -> ProcessIdentity:
    if not isinstance(value, dict):
        return ProcessIdentity()
    files = value.get("files")
    return ProcessIdentity(
        fingerprint=value.get("fingerprint") if isinstance(value.get("fingerprint"), str) else None,
        scope=value.get("scope")
        if isinstance(value.get("scope"), str)
        else "selected_tech_lef_liberty_mapping_not_complete_pdk_closure",
        status=value.get("status")
        if value.get("status") in {"available", "partial", "unknown"}
        else "unknown",
        files=[
            item
            for item in (files if isinstance(files, list) else [])
            if isinstance(item, dict)
            and isinstance(item.get("role"), str)
            and isinstance(item.get("sha256"), str)
            and type(item.get("bytes")) is int
            and item["bytes"] >= 0
        ],
        reason=value.get("reason") if isinstance(value.get("reason"), str) else None,
    )
