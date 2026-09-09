"""Physical QoR record dimensions Q_T, Q_I, Q_A, Q_P, Q_R (spec §8).

Qphys = (Q_T, Q_I, Q_A, Q_P, Q_R) with each coordinate in [0, 100] or
None (explicit UNKNOWN). Physical quality is never conflated with
signoff feasibility: a failing design still reports continuous quality
coordinates while the scalar projection is vetoed to zero elsewhere.
"""

from chipcompiler.analysis.qor.calibration import (
    GUARDBAND_FRACTION,
    OVER_PROVISION_FRACTION,
    TAU_AREA_FAIL,
    TAU_AREA_MAX,
    TAU_AREA_MIN,
    TAU_I_FAIL,
    TAU_I_PREF,
    TIMING_FAIL_FRACTION,
    W_CTS_IMBALANCE,
    W_PVT_DISPERSION,
    clamp01,
    psi_cost,
    psi_target,
)
from chipcompiler.analysis.qor.compatibility import EXACT_COMPATIBLE
from chipcompiler.analysis.qor.models import QorDimension

_QUALITY_DIMENSIONS = ("timing", "interconnect", "area", "power", "robustness")


def _quality_state(value):
    """Policy mapping from a continuous [0, 100] quality coordinate."""
    if value is None:
        return "UNKNOWN"
    if value >= 80.0:
        return "PASS"
    if value >= 60.0:
        return "WATCH"
    return "FAIL"


def _timing_state(ws, tclk):
    """TimingState classification (spec eq. 23)."""
    if ws is None or not tclk:
        return "UNKNOWN"
    if ws < 0:
        return "FAIL"
    if ws < GUARDBAND_FRACTION * tclk:
        return "WATCH"
    if ws > OVER_PROVISION_FRACTION * tclk:
        return "OPPORTUNITY"
    return "PASS"


def _timing(bundle, inputs):
    ws = inputs.value("sta_setup_wns")
    tclk = inputs.tclk_ns
    value = None
    if ws is not None and tclk:
        if ws < 0:
            value = 50.0 * max(0.0, 1.0 - abs(ws) / (TIMING_FAIL_FRACTION * tclk))
        else:
            value = 50.0 + 50.0 * clamp01(ws / (GUARDBAND_FRACTION * tclk))
    features = [bundle.features["F_STA_HEADROOM"]]
    return QorDimension(key="timing", value=value, state=_timing_state(ws, tclk), features=features)


def _interconnect(bundle, inputs):
    # D-C ladder: score I_total under verified compatibility, else the
    # same-netlist I_place with the degraded evidence carried by the
    # compatibility contract on the feature records.
    inflation = (
        bundle.i_total if bundle.compatibility.status == EXACT_COMPATIBLE else bundle.i_place
    )
    value = None
    if inflation is not None:
        congestion = bundle.congestion_severity if bundle.congestion_severity is not None else 0.0
        value = 100.0 * psi_cost(inflation, TAU_I_PREF, TAU_I_FAIL) * (1.0 - min(1.0, congestion))
    features = [
        bundle.features["F_PL_I_PLACE"],
        bundle.features["F_RT_I_ROUTE"],
        bundle.features["F_RT_I_TOTAL"],
        bundle.features["F_PL_CONG_CONC"],
        bundle.features["F_RT_VIA_DENSITY"],
        bundle.features["F_RCX_CPL_FRAC"],
    ]
    return QorDimension(
        key="interconnect", value=value, state=_quality_state(value), features=features
    )


def _area(bundle, inputs):
    utilization = inputs.value("core_utilization")
    value = None
    if utilization is not None:
        value = 100.0 * psi_target(utilization, TAU_AREA_MIN, TAU_AREA_MAX, TAU_AREA_FAIL)
    return QorDimension(
        key="area",
        value=value,
        state=_quality_state(value),
        features=[bundle.features["F_PLAN_DENSITY"]],
    )


def _power(bundle, inputs):
    budget = inputs.power_budget_uw
    total = inputs.power_total_uw
    value = None
    if budget is not None and total is not None:
        value = 100.0 * clamp01((budget - total) / budget)
    return QorDimension(
        key="power",
        value=value,
        state=_quality_state(value),
        features=[bundle.features["F_SYN_LEAK_FRAC"]],
    )


def _robustness(bundle, inputs):
    imbalance = bundle.cts_imbalance
    candidates = [d for d in (bundle.pvt_setup_disp, bundle.pvt_hold_disp) if d is not None]
    pvt = max(candidates) if candidates else None

    contributors = []
    if imbalance is not None:
        contributors.append(W_CTS_IMBALANCE * imbalance)
    if pvt is not None:
        contributors.append(W_PVT_DISPERSION * min(1.0, pvt))
    value = None
    if contributors:
        used_weight = W_CTS_IMBALANCE if imbalance is not None else 0.0
        used_weight += W_PVT_DISPERSION if pvt is not None else 0.0
        # Re-normalize over available contributors (spec §8.2.5 fallback).
        value = 100.0 * (1.0 - sum(contributors) / used_weight)
    return QorDimension(
        key="robustness",
        value=value,
        state=_quality_state(value),
        features=[
            bundle.features["F_CTS_BUF_IMBAL"],
            bundle.features["F_STA_PVT_SETUP_DISP"],
            bundle.features["F_STA_PVT_HOLD_DISP"],
            bundle.features["F_STA_PVT_MAX_DISP"],
        ],
    )


def evaluate_dimensions(bundle, inputs) -> dict:
    dimensions = {}
    for builder in (_timing, _interconnect, _area, _power, _robustness):
        dimension = builder(bundle, inputs)
        dimensions[dimension.key] = dimension
    return dimensions
