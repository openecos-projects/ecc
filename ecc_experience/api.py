from pathlib import Path

from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.collection.collect import CollectionResult, collect_committed_case
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.verify import verify_case
from ecc_experience.models import ExperienceCase, Verification


def collect(workspace: str | Path, store: str | Path) -> CollectionResult:
    return collect_committed_case(workspace, ExperienceStore(store), read_workspace_observation)


def list_cases(store: str | Path) -> list[ExperienceCase]:
    repository = ExperienceStore(store)
    return [repository.read(case_id) for case_id in repository.list_ids()]


def show(case_id: str, store: str | Path) -> ExperienceCase:
    return ExperienceStore(store).read(case_id)


def verify(case_id: str, store: str | Path) -> Verification:
    repository = ExperienceStore(store)
    return verify_case(repository.read(case_id), repository.case_directory(case_id))
