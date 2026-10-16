"""Resolve the fixed timing policy of a standalone optimization step."""

import math

from chipcompiler.data.config_params.dreamplace_sizing import DEFAULT_DIFF_SIZING_COEFFICIENTS


def resolve_timing_coefficients(params: dict, key: str) -> dict:
    policy = params.get(key, {})
    if not isinstance(policy, dict) or set(policy) - DEFAULT_DIFF_SIZING_COEFFICIENTS.keys():
        raise ValueError(f"{key} must be an object with wns, tns, cap, slew")
    coefficients = DEFAULT_DIFF_SIZING_COEFFICIENTS | policy
    for name, value in coefficients.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(f"{key}.{name} must be finite and nonnegative")
    return coefficients
