"""Scalar summary projection and design-intent profiles (spec §9).

Qsummary is a profile-dependent display projection, never an objective
physical truth. The feasibility veto is absolute: a physical signoff
failure forces score 0.0 so that excellent area or power can never mask
an unmanufacturable chip; unevaluated evidence yields NOT_RATED instead
of a fabricated number.
"""

from chipcompiler.analysis.qor.models import ScalarSummary

_BALANCED = "balanced"
_TIMING_CRITICAL = "timing_critical"
_LOW_POWER = "low_power"
_AREA_OPTIMIZED = "area_optimized"

# Dimension weights per design-intent profile (spec Table 5).
PROFILES = {
    _BALANCED: {
        "timing": 0.30,
        "interconnect": 0.25,
        "area": 0.15,
        "power": 0.15,
        "robustness": 0.15,
    },
    _TIMING_CRITICAL: {
        "timing": 0.45,
        "interconnect": 0.20,
        "area": 0.10,
        "power": 0.10,
        "robustness": 0.15,
    },
    _LOW_POWER: {
        "timing": 0.20,
        "interconnect": 0.15,
        "area": 0.15,
        "power": 0.35,
        "robustness": 0.15,
    },
    _AREA_OPTIMIZED: {
        "timing": 0.20,
        "interconnect": 0.25,
        "area": 0.35,
        "power": 0.10,
        "robustness": 0.10,
    },
}

_PHYSICAL_FAIL = "PHYSICAL_FAIL"


def evaluate_scalar_summary(feasibility, dimensions, profile: str) -> ScalarSummary:
    weights = PROFILES.get(profile, PROFILES[_BALANCED])

    if feasibility.status == _PHYSICAL_FAIL:
        return ScalarSummary(score=0.0, status="FAIL", profile=profile, weights=weights)
    if feasibility.status in ("NOT_VERIFIED", "UNKNOWN"):
        return ScalarSummary(score=None, status="NOT_RATED", profile=profile, weights=weights)

    evaluated = {
        key: dimension.value for key, dimension in dimensions.items() if dimension.value is not None
    }
    if not evaluated:
        return ScalarSummary(score=None, status="NOT_RATED", profile=profile, weights=weights)

    # Weights re-normalize over evaluated dimensions so that a missing
    # optional coordinate (e.g. power without a declared budget) cannot
    # silently compress the score scale.
    used_weight = sum(weights[key] for key in evaluated)
    if used_weight <= 0:
        return ScalarSummary(score=None, status="NOT_RATED", profile=profile, weights=weights)
    score = sum(weights[key] * value for key, value in evaluated.items()) / used_weight
    return ScalarSummary(score=score, status=_status(score), profile=profile, weights=weights)


def _status(score: float) -> str:
    if score >= 90.0:
        return "GREEN"
    if score >= 75.0:
        return "YELLOW"
    if score >= 60.0:
        return "ORANGE"
    return "RED"
