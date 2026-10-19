"""Bind explicit historical execution evidence to the actual source workspace."""

from pathlib import Path

from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.verify import verify_case
from ecc_experience.models import ExperienceCase, ExperienceError


def bind_baseline(observed: ExperienceCase, case_id: str | None, store) -> ExperienceCase:
    if case_id is None:
        return observed
    repository = ExperienceStore(store)
    selected = repository.read(case_id)
    if (
        verify_case(selected, repository.case_directory(case_id)).status != "pass"
        or selected.source.snapshot_digest != observed.source.snapshot_digest
        or Path(selected.source.workspace_root).resolve()
        != Path(observed.source.workspace_root).resolve()
        or selected.input_content_fingerprint != observed.input_content_fingerprint
        or selected.facts.get("workspaceSpec") != observed.facts.get("workspaceSpec")
    ):
        raise ExperienceError(
            "Baseline case must be verified evidence of this exact committed workspace",
            code="experience_plan_invalid",
        )
    return selected
