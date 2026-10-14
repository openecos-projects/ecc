from pathlib import Path

from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.benchmark.ledger import initialize as initialize_campaign
from ecc_experience.benchmark.ledger import record_trial as record_campaign_trial
from ecc_experience.benchmark.ledger import status as read_campaign_status
from ecc_experience.benchmark.manifest import load_manifest
from ecc_experience.collection.collect import CollectionResult, collect_committed_case
from ecc_experience.collection.drain import drain as drain_recording
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.verify import verify_case
from ecc_experience.models import ExperienceCase, Verification
from ecc_experience.recording import disable as disable_recording
from ecc_experience.recording import set_enabled
from ecc_experience.recording import status as recording_status


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


def enable(project: str | Path, store: str | Path):
    return set_enabled(project, store=store, enabled=True)


def disable(project: str | Path):
    return disable_recording(project)


def status(project: str | Path) -> dict:
    return recording_status(project)


def drain(project: str | Path, *, limit: int = 32) -> list[dict]:
    return drain_recording(project, limit=limit)


def validate_campaign(manifest: str | Path) -> dict:
    _validated, summary = load_manifest(manifest)
    return summary


def init_campaign(manifest: str | Path, ledger: str | Path | None = None) -> dict:
    return initialize_campaign(manifest, ledger)


def record_trial(
    ledger: str | Path,
    *,
    design_id: str,
    workspace: str,
    status: str,
    trial_id: str | None = None,
    case_id: str | None = None,
    reason: str | None = None,
) -> dict:
    return record_campaign_trial(
        ledger,
        design_id=design_id,
        workspace=workspace,
        status=status,
        trial_id=trial_id,
        case_id=case_id,
        reason=reason,
    )


def campaign_status(manifest: str | Path, ledger: str | Path | None = None) -> dict:
    return read_campaign_status(manifest, ledger)
