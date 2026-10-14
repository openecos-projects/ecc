"""Compare verified experience cases without executing EDA."""

import math
from pathlib import Path

from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.verify import verify_case


def evaluate(baseline_id: str, candidate_id: str, store: str | Path) -> dict:
    repository = ExperienceStore(store)
    baseline = repository.read(baseline_id)
    candidate = repository.read(candidate_id)
    baseline_verification = verify_case(
        baseline, repository.case_directory(baseline.case_id)
    )
    candidate_verification = verify_case(
        candidate, repository.case_directory(candidate.case_id)
    )
    result = {
        "baseline_case_id": baseline.case_id,
        "candidate_case_id": candidate.case_id,
        "status": "insufficient_evidence",
        "comparison": "unavailable",
        "baseline_verification": baseline_verification.model_dump(),
        "candidate_verification": candidate_verification.model_dump(),
        "baseline_input_content_fingerprint": baseline.input_content_fingerprint,
        "candidate_input_content_fingerprint": candidate.input_content_fingerprint,
    }
    if not _comparable_inputs(
        baseline.input_content_fingerprint, candidate.input_content_fingerprint
    ):
        result["status"] = "incompatible"
        result["reason"] = "Cases do not have matching input content fingerprints"
        return result
    if any(
        verification.status == "fail" or verification.integrity == "fail"
        for verification in (baseline_verification, candidate_verification)
    ):
        result["reason"] = "Both cases require evidence verification without failures"
        return result
    baseline_score = _score(baseline.facts)
    candidate_score = _score(candidate.facts)
    if baseline_score is None or candidate_score is None:
        result["reason"] = "Both cases require an available numeric QoR score"
        return result
    delta = candidate_score - baseline_score
    result.update(
        {
            "status": "complete",
            "comparison": (
                "improved" if delta > 0 else "regressed" if delta < 0 else "unchanged"
            ),
            "direction": "higher_is_better",
            "baseline_score": baseline_score,
            "candidate_score": candidate_score,
            "score_delta": delta,
            "score_delta_percent": (delta / baseline_score * 100)
            if baseline_score != 0
            else None,
        }
    )
    return result


def _comparable_inputs(baseline: str | None, candidate: str | None) -> bool:
    return baseline is not None and baseline == candidate


def _score(facts: dict) -> float | None:
    qor = facts.get("qorSnapshotExtension")
    if not isinstance(qor, dict):
        return None
    score = qor.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score):
        return None
    return float(score)
