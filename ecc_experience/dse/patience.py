"""Resolve and validate the early-stopping patience policy for DSE plans."""

import math

from ecc_experience.models import ExperienceError

AUTO_PATIENCE = "auto"
AUTO_RULE = "candidate_fraction_v1"


def resolve_patience(
    requested: int | str,
    *,
    strategy: str,
    domain_size: int,
    screening_trials: int,
) -> tuple[int, dict]:
    if strategy not in {"grid", "adaptive"}:
        raise ExperienceError("Unsupported DSE strategy", code="experience_plan_invalid")
    if domain_size < 1 or screening_trials < 1:
        raise ExperienceError(
            "DSE patience requires a non-empty candidate domain",
            code="experience_plan_invalid",
        )
    if requested == AUTO_PATIENCE:
        if strategy == "grid":
            resolved = screening_trials
        else:
            startup_floor = min(6, screening_trials)
            resolved = max(startup_floor, math.ceil(screening_trials / 2))
        return resolved, {
            "mode": "auto",
            "requested": AUTO_PATIENCE,
            "rule": AUTO_RULE,
            "strategy": strategy,
            "domain_size": domain_size,
            "screening_trials": screening_trials,
            "resolved": resolved,
        }
    if type(requested) is not int or requested < 1:
        raise ExperienceError(
            "DSE patience must be a positive integer or 'auto'",
            code="experience_plan_invalid",
        )
    return requested, {
        "mode": "fixed",
        "requested": requested,
        "strategy": strategy,
        "domain_size": domain_size,
        "screening_trials": screening_trials,
        "resolved": requested,
    }
