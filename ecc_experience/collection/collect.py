from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from ecc_experience import __version__
from ecc_experience.files import case_identity, digest
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.models import ExperienceCase, ExperienceError, WorkspaceObservation


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
        )
    inputs = [item.model_dump() for item in observation.inputs]
    spec = observation.facts.get("workspaceSpec", {})
    fingerprint = None
    if inputs and all(item["sha256"] is not None for item in inputs):
        fingerprint = digest({"top": spec.get("design", {}).get("topModule"), "inputs": inputs})
    case = ExperienceCase(
        case_id="",
        collector_version=__version__,
        collected_at=datetime.now(UTC).isoformat(),
        source=observation.source,
        input_content_fingerprint=fingerprint,
        inputs=observation.inputs,
        facts=observation.facts,
        evidence=observation.evidence,
        limitations=observation.limitations,
        parameter_evidence="configured" if spec.get("parameters") else "unknown",
        validation_scope="committed_observation"
        if observation.source.observation_type == "committed_import"
        else "legacy_import",
    )
    case = case.model_copy(update={"case_id": case_identity(case.model_dump())})
    status = store.put(case, observation.copies)
    return CollectionResult(case=store.read(case.case_id), status=status)
