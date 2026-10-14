"""Read-only summaries joining campaign trials with experience evidence."""

from pathlib import Path

from ecc_experience.benchmark.ledger import status as campaign_status
from ecc_experience.benchmark.manifest import load_manifest
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.verify import verify_case


def summarize(manifest: str | Path, ledger: str | Path | None = None) -> dict:
    _model, manifest_summary = load_manifest(manifest)
    progress = campaign_status(manifest, ledger)
    repository = ExperienceStore(manifest_summary["store"])
    trials = []
    evidence_counts = {"available": 0, "missing": 0, "fail": 0, "unknown": 0}
    for design in progress["designs"]:
        latest = design["latest_trial"]
        if latest is None:
            trials.append({"design_id": design["id"], "status": "pending"})
            continue
        record = {
            "design_id": design["id"],
            "trial_id": latest["trial_id"],
            "workspace": latest["workspace"],
            "status": latest["status"],
            "case_id": latest.get("case_id"),
            "reason": latest.get("reason"),
        }
        case_id = latest.get("case_id")
        if case_id is None:
            record["evidence_status"] = "missing"
            evidence_counts["missing"] += 1
        else:
            try:
                case = repository.read(case_id)
                verification = verify_case(case, repository.case_directory(case_id))
                record["evidence_status"] = verification.status
                record["integrity"] = verification.integrity
                record["qor"] = _qor_summary(case.facts)
                evidence_counts[verification.status] += 1
            except (OSError, ValueError):
                record["evidence_status"] = "missing"
                evidence_counts["missing"] += 1
        trials.append(record)
    return {
        "campaign_id": progress["campaign_id"],
        "ledger": progress["ledger"],
        "campaign_status": _campaign_state(progress["counts"]),
        "manifest_match": progress["manifest_match"],
        "counts": progress["counts"],
        "evidence_counts": evidence_counts,
        "trials": trials,
    }


def _campaign_state(counts: dict) -> str:
    if counts["pending"] or counts["running"]:
        return "in_progress"
    if counts["fail"] or counts["blocked"]:
        return "completed_with_failures"
    if counts["cancelled"]:
        return "completed_with_cancellations"
    return "complete"


def _qor_summary(facts: dict) -> dict:
    qor = facts.get("qorSnapshotExtension")
    if not isinstance(qor, dict):
        return {}
    return {key: qor[key] for key in ("score", "status", "reason", "source") if key in qor}
