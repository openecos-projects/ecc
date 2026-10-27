"""Detect evidence drift and produce reversible retirement recommendations."""

import math
from pathlib import Path
from typing import Any

from ecc_experience.files import digest, read_json
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.plan import write_plan

DRIFT_SCHEMA = "ecc-experience-drift-report/1"
OBSERVATION_SCHEMA = "ecc-experience-drift-observation/1"


def assess_drift(observation_path: str | Path, output: str | Path) -> dict[str, Any]:
    source = Path(observation_path).expanduser().absolute()
    payload = read_json(source, 16 * 1024 * 1024)
    baseline, current, thresholds = _payload(payload)
    rows = [
        _metric(name, baseline.get(name), current.get(name), limit)
        for name, limit in thresholds.items()
    ]
    statuses = {row["status"] for row in rows}
    status = "drift" if "drift" in statuses else "unknown" if "unknown" in statuses else "stable"
    retire = payload.get("retire_rules", [])
    keep = payload.get("keep_rules", [])
    if not _strings(retire) or not _strings(keep):
        raise _invalid("Rule lists must contain non-empty strings")
    actions = [
        {
            "rule_id": rule_id,
            "action": "downgrade_to_experimental" if status == "drift" else "keep",
            "reason": "measured drift exceeds declared threshold"
            if status == "drift"
            else "no threshold breach",
        }
        for rule_id in sorted(set(keep))
    ]
    actions.extend(
        {
            "rule_id": rule_id,
            "action": "retired" if status == "drift" else "keep",
            "reason": "drift retirement rule activated"
            if status == "drift"
            else "retirement condition not met",
        }
        for rule_id in sorted(set(retire))
    )
    result = {
        "schema": DRIFT_SCHEMA,
        "observation_sha256": digest(payload),
        "status": status,
        "metrics": rows,
        "actions": actions,
        "policy": {
            "automatic_apply": False,
            "historical_evidence_preserved": True,
            "reason": (
                "Drift only changes recommendation eligibility; case and release evidence "
                "is immutable"
            ),
        },
        "safe_to_apply": False,
    }
    destination = Path(output).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise _invalid("Drift output must be a new file")
    write_plan(destination, result)
    return result


def _payload(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if payload.get("schema") != OBSERVATION_SCHEMA:
        raise _invalid("Invalid drift observation schema")
    baseline = payload.get("baseline")
    current = payload.get("current")
    thresholds = payload.get("thresholds")
    if not all(isinstance(value, dict) for value in (baseline, current, thresholds)):
        raise _invalid("Drift baseline, current and thresholds must be objects")
    assert isinstance(baseline, dict)
    assert isinstance(current, dict)
    assert isinstance(thresholds, dict)
    if not thresholds:
        raise _invalid("Drift thresholds cannot be empty")
    if not all(_number(value) and value >= 0 for value in thresholds.values()):
        raise _invalid("Drift thresholds must be non-negative finite numbers")
    return baseline, current, thresholds


def _metric(name: str, baseline: Any, current: Any, limit: Any) -> dict[str, Any]:
    if not _number(baseline) or not _number(current):
        return {
            "metric": name,
            "status": "unknown",
            "baseline": baseline if _number(baseline) else None,
            "current": current if _number(current) else None,
            "relative_change": None,
            "threshold": float(limit),
        }
    denominator = max(abs(float(baseline)), 1e-12)
    change = abs(float(current) - float(baseline)) / denominator
    return {
        "metric": name,
        "status": "drift" if change > float(limit) else "stable",
        "baseline": float(baseline),
        "current": float(current),
        "relative_change": change,
        "threshold": float(limit),
    }


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item for item in value)


def _number(value: Any) -> bool:
    return type(value) in {int, float} and math.isfinite(value)


def _invalid(reason: str) -> ExperienceError:
    return ExperienceError(reason, code="experience_drift_invalid")
