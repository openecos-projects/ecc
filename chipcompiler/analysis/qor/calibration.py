"""Calibration functions and default threshold constants (spec §3.2, §8).

Two mathematical classes exist and are never interchanged:

* ``psi_cost`` — one-sided monotone non-increasing cost calibration for
  lower-is-better quantities that have a preferred plateau (interconnect
  inflation, power budget consumption, timing violation scale). Values at
  or below the preferred threshold receive full credit; approaching the
  geometric lower bound is never penalized.
* ``psi_target`` — two-sided target-interval calibration for parameters
  where both under- and over-allocation are sub-optimal (placed core
  utilization). ``tau_min > 0`` keeps the under-allocation branch
  well-defined, so metrics whose preferred lower bound is zero-adjacent
  (inflation >= 1.0) must use ``psi_cost`` instead.

Default thresholds are CALIBRATED_HEURISTIC values from the spec. They
are engineering defaults, not physical laws; every consumer must present
them as calibrated policy.
"""

from math import isfinite


class CalibrationError(ValueError):
    """Raised when calibration parameters violate their ordering contract."""


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def psi_cost(value: float, tau_pref: float, tau_fail: float) -> float:
    """One-sided monotone cost calibration (spec eq. 10)."""
    if not (_finite(tau_pref) and _finite(tau_fail)) or not tau_pref < tau_fail:
        raise CalibrationError(f"require tau_pref < tau_fail, got {tau_pref!r}, {tau_fail!r}")
    if not _finite(value):
        raise CalibrationError(f"non-finite calibration input: {value!r}")
    if value <= tau_pref:
        return 1.0
    if value >= tau_fail:
        return 0.0
    return (tau_fail - value) / (tau_fail - tau_pref)


def psi_target(value: float, tau_min: float, tau_max: float, tau_fail: float) -> float:
    """Two-sided target-interval calibration (spec eq. 11)."""
    if not (_finite(tau_min) and _finite(tau_max) and _finite(tau_fail)):
        raise CalibrationError("target-interval thresholds must be finite numbers")
    if not 0 < tau_min <= tau_max < tau_fail:
        raise CalibrationError(
            f"require 0 < tau_min <= tau_max < tau_fail, got {tau_min!r}, {tau_max!r}, {tau_fail!r}"
        )
    if not _finite(value):
        raise CalibrationError(f"non-finite calibration input: {value!r}")
    if tau_min <= value <= tau_max:
        return 1.0
    if value < tau_min:
        return value / tau_min
    return max(0.0, min(1.0, (tau_fail - value) / (tau_fail - tau_max)))


def clamp01(value: float) -> float:
    if not _finite(value):
        raise CalibrationError(f"non-finite clamp input: {value!r}")
    return max(0.0, min(1.0, value))


# --- Default calibration constants (spec §8) ---------------------------------

# Interconnect inflation (I_total, and I_place under the D-C ladder).
TAU_I_PREF = 1.25
TAU_I_FAIL = 1.75

# Placed core utilization target interval.
TAU_AREA_MIN = 0.45
TAU_AREA_MAX = 0.70
TAU_AREA_FAIL = 0.85

# Robustness: structural clock imbalance vs multi-corner PVT dispersion.
W_CTS_IMBALANCE = 0.5
W_PVT_DISPERSION = 0.5

# Congestion severity normalization (spec eq. 21).
TAU_RUDY_FAIL = 1.0
TAU_EGR_MAX_FAIL = 20.0
TAU_EGR_TOTAL_FAIL = 100.0

# Timing fractions of Tclk (USER_PROJECT_CONSTRAINT / CALIBRATED_HEURISTIC).
GUARDBAND_FRACTION = 0.05
TIMING_FAIL_FRACTION = 0.20
OVER_PROVISION_FRACTION = 0.20

# Signoff-gate severity normalization references (spec eq. 52-54).
TAU_DRC_REF = 100.0
TAU_LVS_REF = 50.0
HARDEN_DELIVERABLE_COUNT = 3  # GDS, LEF, LIB

# Feature watch levels for robustness contributors (POLICY threshold):
# a contributor consuming less than 10% of its dimension budget is clean.
ROBUSTNESS_CONTRIBUTOR_WATCH = 0.10
