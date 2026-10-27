"""Compare champion and challenger releases without publishing either one."""

import math
from pathlib import Path
from typing import Any

from ecc_experience.files import digest, read_json
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.plan import write_plan

CHAMPION_SCHEMA = "ecc-experience-champion-report/1"
SPEC_SCHEMA = "ecc-experience-champion-spec/1"
MIN_DESIGNS = 6
MIN_FAMILIES = 3


def compare_champion(spec_path: str | Path, output: str | Path) -> dict[str, Any]:
    source = Path(spec_path).expanduser().absolute()
    payload = read_json(source, 16 * 1024 * 1024)
    champion, challenger, thresholds = _payload(payload)
    metrics = sorted(set(champion["metrics"]) | set(challenger["metrics"]))
    deltas = {
        name: _delta(champion["metrics"].get(name), challenger["metrics"].get(name))
        for name in metrics
    }
    reasons = []
    if not payload.get("equal_budget"):
        reasons.append("equal_budget_not_established")
    if champion["design_count"] < MIN_DESIGNS or challenger["design_count"] < MIN_DESIGNS:
        reasons.append("insufficient_independent_designs")
    if champion["family_count"] < MIN_FAMILIES or challenger["family_count"] < MIN_FAMILIES:
        reasons.append("insufficient_families")
    primary = thresholds["primary_metric"]
    primary_delta = deltas.get(primary)
    if primary_delta is None:
        reasons.append("primary_metric_unavailable")
    elif not _improved(primary_delta["delta"], thresholds, primary):
        reasons.append("challenger_did_not_improve_primary_metric")
    for name, threshold in thresholds["max_regressions"].items():
        delta = deltas.get(name)
        if delta is None:
            reasons.append(f"metric_unavailable:{name}")
        elif _regressed(
            delta, thresholds["regression_directions"].get(name, "maximize"), threshold
        ):
            reasons.append(f"metric_regression:{name}")
    status = (
        "unknown"
        if any(reason.startswith("metric_unavailable") for reason in reasons)
        else ("promote_candidate" if not reasons else "retain_champion")
    )
    result = {
        "schema": CHAMPION_SCHEMA,
        "spec_sha256": digest(payload),
        "champion": champion["release_id"],
        "challenger": challenger["release_id"],
        "status": status,
        "reasons": reasons,
        "metrics": deltas,
        "summary": {
            "equal_budget": bool(payload.get("equal_budget")),
            "champion_designs": champion["design_count"],
            "challenger_designs": challenger["design_count"],
            "champion_families": champion["family_count"],
            "challenger_families": challenger["family_count"],
            "thresholds": thresholds,
        },
        "actions": {
            "selected": "challenger" if status == "promote_candidate" else "champion",
            "publish_allowed": False,
            "automatic_publish": False,
            "reason": "A reviewed release command is still required",
        },
        "safe_to_apply": False,
    }
    destination = Path(output).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise _invalid("Champion output must be a new file")
    write_plan(destination, result)
    return result


def _payload(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if payload.get("schema") != SPEC_SCHEMA:
        raise _invalid("Invalid champion specification schema")
    champion = _release(payload.get("champion"))
    challenger = _release(payload.get("challenger"))
    thresholds = payload.get("thresholds")
    if not isinstance(thresholds, dict):
        raise _invalid("Champion thresholds must be an object")
    primary = thresholds.get("primary_metric")
    direction = thresholds.get("primary_direction", "minimize")
    min_improvement = thresholds.get("min_improvement", 0.0)
    max_regressions = thresholds.get("max_regressions", {})
    regression_directions = thresholds.get("regression_directions", {})
    if (
        not isinstance(primary, str)
        or direction not in {"minimize", "maximize"}
        or not _number(min_improvement)
        or min_improvement < 0
        or not isinstance(max_regressions, dict)
        or not all(
            isinstance(key, str) and key and _number(value) and value >= 0
            for key, value in max_regressions.items()
        )
        or not isinstance(regression_directions, dict)
        or not all(
            isinstance(key, str)
            and key in max_regressions
            and direction in {"minimize", "maximize"}
            for key, direction in regression_directions.items()
        )
    ):
        raise _invalid("Invalid champion thresholds")
    return (
        champion,
        challenger,
        {
            "primary_metric": primary,
            "primary_direction": direction,
            "min_improvement": float(min_improvement),
            "max_regressions": {key: float(value) for key, value in max_regressions.items()},
            "regression_directions": dict(regression_directions),
        },
    )


def _release(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("release_id"), str)
        or not value["release_id"]
        or not isinstance(value.get("metrics"), dict)
        or not all(isinstance(key, str) and _number(item) for key, item in value["metrics"].items())
    ):
        raise _invalid("Champion and challenger require release IDs and numeric metrics")
    evidence = value.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    design_count = evidence.get("design_count", 0)
    family_count = evidence.get("family_count", 0)
    if type(design_count) is not int or type(family_count) is not int:
        raise _invalid("Release evidence counts must be integers")
    return {
        "release_id": value["release_id"],
        "metrics": {key: float(item) for key, item in value["metrics"].items()},
        "design_count": design_count,
        "family_count": family_count,
    }


def _improved(delta: float, thresholds: dict[str, Any], name: str) -> bool:
    if thresholds["primary_metric"] != name:
        return True
    if thresholds["primary_direction"] == "minimize":
        return delta <= -thresholds["min_improvement"]
    return delta >= thresholds["min_improvement"]


def _delta(champion: Any, challenger: Any) -> dict[str, float] | None:
    if not _number(champion) or not _number(challenger):
        return None
    return {
        "champion": float(champion),
        "challenger": float(challenger),
        "delta": float(challenger) - float(champion),
    }


def _regressed(delta: dict[str, float], direction: str, threshold: float) -> bool:
    if direction == "minimize":
        return delta["challenger"] - delta["champion"] > threshold
    return delta["champion"] - delta["challenger"] > threshold


def _number(value: Any) -> bool:
    return type(value) in {int, float} and math.isfinite(value)


def _invalid(reason: str) -> ExperienceError:
    return ExperienceError(reason, code="experience_champion_invalid")
