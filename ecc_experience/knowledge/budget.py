"""Scope-aware resource budget estimates with explicit sample thresholds."""

from __future__ import annotations

import math
from pathlib import Path

from ecc_experience.files import digest
from ecc_experience.knowledge.release import verify_release
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.verify import verify_case
from ecc_experience.models import ExperienceCase, ExperienceError

BUDGET_SCHEMA = "resource-budget/1"
MIN_SAMPLES = 8
COVERAGE_TARGET = 0.8
SAFETY_MARGIN = 1.2


def resource_budget(
    case_id: str,
    store: str | Path,
    *,
    release: str | Path | None = None,
    through_step: str,
    host_class: str | None = None,
    concurrency: int | None = None,
    min_samples: int = MIN_SAMPLES,
    coverage_target: float = COVERAGE_TARGET,
    safety_margin: float = SAFETY_MARGIN,
    validation_case_ids: list[str] | None = None,
) -> dict:
    if min_samples < 1 or not 0 < coverage_target <= 1 or safety_margin < 1:
        raise ExperienceError(
            "Resource budget thresholds are invalid", code="experience_budget_invalid"
        )
    repository = ExperienceStore(store)
    query = repository.read(case_id)
    query_scope = _query_scope(query, through_step, host_class, concurrency)
    candidates = _release_case_ids(release, repository) if release is not None else None
    samples: list[dict] = []
    risks = {"failed": 0, "partial": 0, "oom_or_timeout": 0, "unavailable": 0}
    excluded: list[dict] = []
    for candidate_id in repository.list_ids():
        if candidate_id == case_id or (candidates is not None and candidate_id not in candidates):
            continue
        try:
            candidate = repository.read(candidate_id)
            verification = verify_case(candidate, repository.case_directory(candidate_id))
            observation = _step_observation(candidate, through_step)
            if observation is None:
                excluded.append({"case_id": candidate_id, "reason": "step_unavailable"})
                continue
            scope = _observation_scope(candidate, observation)
            if verification.integrity != "pass":
                excluded.append({"case_id": candidate_id, "reason": "evidence_invalid"})
                continue
            if scope["process_fingerprint"] != query_scope["process_fingerprint"]:
                excluded.append({"case_id": candidate_id, "reason": "process_mismatch"})
                continue
            if scope["runtime_fingerprint"] != query_scope["runtime_fingerprint"]:
                excluded.append({"case_id": candidate_id, "reason": "runtime_mismatch"})
                continue
            if scope["host_class"] != query_scope["host_class"]:
                excluded.append({"case_id": candidate_id, "reason": "host_class_mismatch"})
                continue
            if scope["concurrency"] != query_scope["concurrency"]:
                excluded.append({"case_id": candidate_id, "reason": "concurrency_mismatch"})
                continue
            outcome = _outcome(observation, candidate, through_step)
            if outcome in {"cancelled", "oom", "timeout", "failed"}:
                risks["oom_or_timeout" if outcome in {"oom", "timeout"} else "failed"] += 1
                excluded.append({"case_id": candidate_id, "reason": f"outcome:{outcome}"})
                continue
            status = observation.get("status")
            if status != "available":
                risks["partial" if status == "partial" else "unavailable"] += 1
                excluded.append({"case_id": candidate_id, "reason": f"measurement:{status}"})
                continue
            elapsed = _nonnegative(observation.get("elapsed_seconds"))
            peak = _nonnegative(observation.get("peak_rss_bytes"))
            if elapsed is None or peak is None:
                risks["unavailable"] += 1
                excluded.append({"case_id": candidate_id, "reason": "measurement_missing"})
                continue
            samples.append(
                {
                    "case_id": candidate_id,
                    "elapsed_seconds": elapsed,
                    "peak_rss_bytes": peak,
                    "outcome": outcome,
                }
            )
        except (ExperienceError, OSError, KeyError, TypeError, ValueError) as exc:
            excluded.append({"case_id": candidate_id, "reason": str(exc)})
    result = {
        "schema": BUDGET_SCHEMA,
        "status": "unknown" if not samples else "insufficient_evidence",
        "scope": query_scope,
        "samples": len(samples),
        "minimum_samples": min_samples,
        "elapsed_seconds": _empty_percentiles(),
        "peak_rss_bytes": _empty_percentiles(),
        "coverage_target": coverage_target,
        "safety_margin": safety_margin,
        "validation": None,
        "risk": risks,
        "excluded": excluded[:100],
        "limitations": [
            "RSS samples can miss short peaks and double-count shared pages",
            "Only isolated, successful, scope-matching observations are used",
            "Partial/shared measurements and OOM/timeout outcomes are reported as risk",
            "A P90 safety margin is a planning bound, not a guarantee",
        ],
    }
    if len(samples) >= min_samples:
        elapsed = _percentiles([item["elapsed_seconds"] for item in samples])
        peak = _percentiles([item["peak_rss_bytes"] for item in samples])
        result.update(
            status="available",
            elapsed_seconds=elapsed,
            peak_rss_bytes=peak,
        )
    if validation_case_ids and result["status"] == "available":
        validation = validate_budget_coverage(
            case_id,
            repository.root,
            through_step=through_step,
            case_ids=validation_case_ids,
            release=release,
            host_class=host_class,
            concurrency=concurrency,
            min_samples=min_samples,
            safety_margin=safety_margin,
        )
        result["validation"] = validation
        if validation["status"] == "available" and validation["coverage"] < coverage_target:
            result["status"] = "unknown"
            result["limitations"].append("Held-out budget coverage is below the target")
    return result


def validate_budget_coverage(
    query_case_id: str,
    store: str | Path,
    *,
    through_step: str,
    case_ids: list[str],
    release: str | Path | None = None,
    host_class: str | None = None,
    concurrency: int | None = None,
    min_samples: int = MIN_SAMPLES,
    safety_margin: float = SAFETY_MARGIN,
) -> dict:
    repository = ExperienceStore(store)
    query = repository.read(query_case_id)
    query_scope = _query_scope(query, through_step, host_class, concurrency)
    covered = 0
    checked = 0
    unavailable = 0
    rows = []
    for case_id in case_ids:
        if case_id == query_case_id:
            continue
        try:
            case = repository.read(case_id)
            observation = _step_observation(case, through_step)
            if observation is None or observation.get("status") != "available":
                unavailable += 1
                continue
            verification = verify_case(case, repository.case_directory(case_id))
            if verification.integrity != "pass":
                unavailable += 1
                continue
            scope = _observation_scope(case, observation)
            if (
                scope["process_fingerprint"] != query_scope["process_fingerprint"]
                or scope["runtime_fingerprint"] != query_scope["runtime_fingerprint"]
                or scope["host_class"] != query_scope["host_class"]
                or scope["concurrency"] != query_scope["concurrency"]
                or _outcome(observation, case, through_step) != "success"
            ):
                unavailable += 1
                continue
            actual_elapsed = _nonnegative(observation.get("elapsed_seconds"))
            actual_peak = _nonnegative(observation.get("peak_rss_bytes"))
            if actual_elapsed is None or actual_peak is None:
                unavailable += 1
                continue
            exclude = set(case_ids) | {query_case_id}
            budget = _budget_from_store_excluding_scope(
                case,
                repository,
                through_step,
                exclude,
                release=release,
                host_class=host_class,
                concurrency=concurrency,
                min_samples=min_samples,
            )
            if budget["status"] != "available":
                unavailable += 1
                continue
            elapsed_bound = budget["elapsed_seconds"]["p90"] * safety_margin
            peak_bound = budget["peak_rss_bytes"]["p90"] * safety_margin
            passed = actual_elapsed <= elapsed_bound and actual_peak <= peak_bound
            covered += int(passed)
            checked += 1
            rows.append(
                {
                    "case_id": case_id,
                    "covered": passed,
                    "actual_elapsed_seconds": actual_elapsed,
                    "actual_peak_rss_bytes": actual_peak,
                    "elapsed_bound_seconds": elapsed_bound,
                    "peak_rss_bound_bytes": peak_bound,
                }
            )
        except (ExperienceError, OSError, KeyError, TypeError, ValueError) as exc:
            unavailable += 1
            rows.append({"case_id": case_id, "covered": False, "reason": str(exc)})
    return {
        "status": "available" if checked else "insufficient_evidence",
        "samples": checked,
        "coverage": covered / checked if checked else 0.0,
        "unavailable": unavailable,
        "rows": rows[:100],
    }


def _budget_from_store_excluding_scope(
    query: ExperienceCase,
    repository: ExperienceStore,
    through_step: str,
    exclude: set[str],
    *,
    release: str | Path | None,
    host_class: str | None,
    concurrency: int | None,
    min_samples: int,
) -> dict:
    samples = []
    query_scope = _query_scope(query, through_step, host_class, concurrency)
    allowed = _release_case_ids(release, repository) if release is not None else None
    for candidate_id in repository.list_ids():
        if candidate_id in exclude or (allowed is not None and candidate_id not in allowed):
            continue
        candidate = repository.read(candidate_id)
        observation = _step_observation(candidate, through_step)
        if observation is None or observation.get("status") != "available":
            continue
        if _outcome(observation, candidate, through_step) != "success":
            continue
        scope = _observation_scope(candidate, observation)
        if (
            scope["process_fingerprint"] != query_scope["process_fingerprint"]
            or scope["runtime_fingerprint"] != query_scope["runtime_fingerprint"]
            or scope["host_class"] != query_scope["host_class"]
            or scope["concurrency"] != query_scope["concurrency"]
        ):
            continue
        elapsed = _nonnegative(observation.get("elapsed_seconds"))
        peak = _nonnegative(observation.get("peak_rss_bytes"))
        if elapsed is not None and peak is not None:
            samples.append((elapsed, peak))
    if len(samples) < min_samples:
        return {"status": "insufficient_evidence"}
    return {
        "status": "available",
        "elapsed_seconds": _percentiles([item[0] for item in samples]),
        "peak_rss_bytes": _percentiles([item[1] for item in samples]),
    }


def _release_case_ids(release: str | Path, repository: ExperienceStore) -> set[str]:
    frozen = verify_release(release, repository.root)
    if frozen["status"] != "pass":
        raise ExperienceError(
            "Resource budget release did not verify", code="experience_release_unverified"
        )
    return {item["case_id"] for item in frozen["cases"] if item["status"] == "pass"}


def _step_observation(case: ExperienceCase, through_step: str) -> dict | None:
    flow = case.facts.get("flow")
    steps = flow.get("steps") if isinstance(flow, dict) else None
    if not isinstance(steps, list):
        return None
    for step in steps:
        if isinstance(step, dict) and step.get("name") == through_step:
            observation = step.get("resource_observation")
            return observation if isinstance(observation, dict) else {}
    return None


def _query_scope(
    case: ExperienceCase, through_step: str, host_class: str | None, concurrency: int | None
) -> dict:
    observation = _step_observation(case, through_step)
    scope = _observation_scope(case, observation) if observation is not None else {}
    return {
        "process_fingerprint": case.process_fingerprint,
        "runtime_fingerprint": case.toolchain.runtime_fingerprint
        if case.toolchain is not None
        else None,
        "host_class": host_class or scope.get("host_class", "unknown"),
        "step": through_step,
        "concurrency": concurrency if concurrency is not None else scope.get("concurrency", 1),
    }


def _observation_scope(case: ExperienceCase, observation: dict) -> dict:
    host = observation.get("host")
    host = host if isinstance(host, dict) else {}
    concurrency = observation.get("concurrency")
    concurrency = concurrency if isinstance(concurrency, dict) else {}
    logical = host.get("logical_cores") or observation.get("logical_cpu_count")
    total_memory = host.get("total_memory_bytes")
    model = host.get("cpu_model") or "unknown"
    host_class = (
        host.get("host_class")
        if isinstance(host.get("host_class"), str)
        else digest(
            {
                "cpu_model": model,
                "logical_cores": logical,
                "total_memory_bytes": total_memory,
            }
        )
    )
    value = concurrency.get("max_concurrent", concurrency.get("current_flows", 1))
    return {
        "process_fingerprint": case.process_fingerprint,
        "runtime_fingerprint": case.toolchain.runtime_fingerprint
        if case.toolchain is not None
        else None,
        "host_class": host_class,
        "concurrency": value if type(value) is int and value >= 1 else 1,
    }


def _outcome(observation: dict, case: ExperienceCase, step_name: str) -> str:
    outcome = observation.get("outcome")
    if isinstance(outcome, dict):
        status = outcome.get("status")
        if isinstance(status, str):
            return status.casefold()
    if isinstance(outcome, str):
        return outcome.casefold()
    flow = case.facts.get("flow")
    steps = flow.get("steps") if isinstance(flow, dict) else []
    for step in steps if isinstance(steps, list) else []:
        if isinstance(step, dict) and step.get("name") == step_name:
            state = str(step.get("state", "")).casefold()
            if state in {"success", "succeeded"}:
                return "success"
            if state in {"error", "failed", "failure", "incomplete"}:
                return "failed"
            if state in {"cancelled", "canceled", "interrupted"}:
                return "cancelled"
    return "unknown"


def _percentiles(values: list[float]) -> dict:
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "p50": _quantile(ordered, 0.5),
        "p90": _quantile(ordered, 0.9),
        "max": ordered[-1],
        "count": len(ordered),
    }


def _quantile(values: list[float], quantile: float) -> float:
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _empty_percentiles() -> dict:
    return {"min": None, "p50": None, "p90": None, "max": None, "count": 0}


def _nonnegative(value: object) -> float | None:
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    ):
        return float(value)
    return None
