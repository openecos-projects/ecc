"""Evaluate whether two runtime cohorts are comparable under measured evidence."""

import math
from pathlib import Path
from typing import Any

from ecc_experience.files import digest, read_json
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.plan import write_plan

BRIDGE_SCHEMA = "ecc-experience-bridge-report/1"
SPEC_SCHEMA = "ecc-experience-bridge-spec/1"
MIN_DESIGNS = 3
MIN_FAMILIES = 2


def evaluate_bridge(spec_path: str | Path, output: str | Path) -> dict[str, Any]:
    source = Path(spec_path).expanduser().absolute()
    payload = read_json(source, 16 * 1024 * 1024)
    designs = _designs(payload)
    thresholds = _thresholds(payload.get("thresholds", {}))
    rows = [_design_result(item, thresholds) for item in designs]
    reasons = []
    if len({item["design"] for item in designs}) < MIN_DESIGNS:
        reasons.append("insufficient_independent_designs")
    if len({item["family"] for item in designs}) < MIN_FAMILIES:
        reasons.append("insufficient_families")
    if len({item["input_fingerprint"] for item in designs}) != len(designs):
        reasons.append("duplicate_input_fingerprint")
    if any(row["status"] == "fail" for row in rows):
        reasons.append("bridge_regression")
    if any(row["status"] == "unknown" for row in rows):
        reasons.append("bridge_evidence_unknown")
    status = "fail" if "bridge_regression" in reasons else "unknown" if reasons else "pass"
    result = {
        "schema": BRIDGE_SCHEMA,
        "spec_sha256": digest(payload),
        "baseline_cohort": payload.get("baseline_cohort"),
        "candidate_cohort": payload.get("candidate_cohort"),
        "status": status,
        "reasons": reasons,
        "summary": {
            "design_count": len({item["design"] for item in designs}),
            "family_count": len({item["family"] for item in designs}),
            "pass_count": sum(row["status"] == "pass" for row in rows),
            "unknown_count": sum(row["status"] == "unknown" for row in rows),
            "fail_count": sum(row["status"] == "fail" for row in rows),
            "thresholds": thresholds,
        },
        "designs": rows,
        "cohort_recommendation": ("compatible_experimental" if status == "pass" else "candidate"),
        "promotion_allowed": False,
        "safe_to_apply": False,
        "limitations": [
            "A bridge pass supports comparability, not an automatic cohort promotion",
            "The report does not rewrite historical cases or releases",
        ],
    }
    destination = Path(output).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise _invalid("Bridge output must be a new file")
    write_plan(destination, result)
    return result


def _designs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if (
        payload.get("schema") != SPEC_SCHEMA
        or not isinstance(payload.get("baseline_cohort"), str)
        or not isinstance(payload.get("candidate_cohort"), str)
        or not isinstance(payload.get("designs"), list)
        or not payload["designs"]
    ):
        raise _invalid("Invalid bridge specification")
    result = []
    for item in payload["designs"]:
        if (
            not isinstance(item, dict)
            or not all(
                isinstance(item.get(key), str) and item[key]
                for key in ("design", "family", "input_fingerprint")
            )
            or not isinstance(item.get("metrics"), dict)
        ):
            raise _invalid("Invalid bridge design entry")
        result.append(item)
    return result


def _thresholds(value: Any) -> dict[str, float]:
    defaults = {
        "max_qor_regression": 0.0,
        "min_rank_consistency": 0.8,
        "max_residual_increase": 0.0,
        "min_interval_coverage_delta": 0.0,
        "max_search_regret_increase": 0.0,
        "max_first_feasible_increase_seconds": 0.0,
        "max_resource_error": 0.2,
    }
    if not isinstance(value, dict):
        raise _invalid("Bridge thresholds must be an object")
    unknown = set(value) - set(defaults)
    if unknown:
        raise _invalid(f"Unknown bridge threshold: {sorted(unknown)[0]}")
    result = {**defaults, **value}
    if not all(_number(item) for item in result.values()):
        raise _invalid("Bridge thresholds must be finite numbers")
    thresholds = {key: float(value) for key, value in result.items()}
    if not 0 <= thresholds["min_rank_consistency"] <= 1:
        raise _invalid("Bridge rank consistency threshold must be between 0 and 1")
    if not -1 <= thresholds["min_interval_coverage_delta"] <= 1:
        raise _invalid("Bridge interval coverage delta must be between -1 and 1")
    non_negative = set(defaults) - {"min_rank_consistency", "min_interval_coverage_delta"}
    if any(thresholds[key] < 0 for key in non_negative):
        raise _invalid("Bridge regression thresholds must be non-negative")
    return thresholds


def _design_result(item: dict[str, Any], thresholds: dict[str, float]) -> dict[str, Any]:
    metrics = item["metrics"]
    checks = {
        "qor_delta": _check(
            metrics.get("qor_delta"),
            lambda value: value >= -thresholds["max_qor_regression"],
            "candidate QoR regression exceeds threshold",
        ),
        "rank_consistency": _check(
            metrics.get("rank_consistency"),
            lambda value: value >= thresholds["min_rank_consistency"],
            "rank consistency is below threshold",
        ),
        "residual_delta": _check(
            metrics.get("residual_delta"),
            lambda value: value <= thresholds["max_residual_increase"],
            "model residual increased beyond threshold",
        ),
        "interval_coverage_delta": _check(
            metrics.get("interval_coverage_delta"),
            lambda value: value >= thresholds["min_interval_coverage_delta"],
            "interval coverage regressed beyond threshold",
        ),
        "search_regret_delta": _check(
            metrics.get("search_regret_delta"),
            lambda value: value <= thresholds["max_search_regret_increase"],
            "search regret increased beyond threshold",
        ),
        "first_feasible_delta_seconds": _check(
            metrics.get("first_feasible_delta_seconds"),
            lambda value: value <= thresholds["max_first_feasible_increase_seconds"],
            "first feasible time increased beyond threshold",
        ),
        "resource_error": _check(
            metrics.get("resource_error"),
            lambda value: 0 <= value <= thresholds["max_resource_error"],
            "resource prediction error exceeds threshold",
        ),
    }
    statuses = {value["status"] for value in checks.values()}
    status = "fail" if "fail" in statuses else "unknown" if "unknown" in statuses else "pass"
    return {
        "design": item["design"],
        "family": item["family"],
        "input_fingerprint": item["input_fingerprint"],
        "status": status,
        "checks": checks,
    }


def _check(value: Any, predicate: Any, reason: str) -> dict[str, Any]:
    if not _number(value):
        return {"status": "unknown", "value": None, "reason": "Metric is unavailable"}
    passed = predicate(float(value))
    return {
        "status": "pass" if passed else "fail",
        "value": float(value),
        "reason": None if passed else reason,
    }


def _number(value: Any) -> bool:
    return type(value) in {int, float} and math.isfinite(value)


def _invalid(reason: str) -> ExperienceError:
    return ExperienceError(reason, code="experience_bridge_invalid")
