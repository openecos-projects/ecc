"""Level-2/Level-3 derived feature computation (spec §6).

Every division demands an explicit finite, positive denominator; when a
denominator is zero, missing, or non-finite the feature evaluates to
None with state UNKNOWN — epsilon padding is prohibited because it
destroys exact algebraic identities. Cross-stage route ratios stay
UNKNOWN unless net compatibility is EXACT (D-C ladder).
"""

import dataclasses

from chipcompiler.analysis.qor import feature_registry
from chipcompiler.analysis.qor.calibration import (
    ROBUSTNESS_CONTRIBUTOR_WATCH,
    TAU_EGR_MAX_FAIL,
    TAU_EGR_TOTAL_FAIL,
    TAU_I_FAIL,
    TAU_I_PREF,
    TAU_RUDY_FAIL,
)
from chipcompiler.analysis.qor.compatibility import EXACT_COMPATIBLE, Compatibility
from chipcompiler.analysis.qor.models import SourceArtifact


@dataclasses.dataclass
class FeatureBundle:
    features: dict  # feature id -> FeatureRecord
    # Raw scalars reused by dimension/evaluation layers.
    i_place: float | None = None
    i_route: float | None = None
    i_total: float | None = None
    congestion_severity: float | None = None
    cts_imbalance: float | None = None
    pvt_setup_disp: float | None = None
    pvt_hold_disp: float | None = None
    compatibility: "Compatibility | None" = None
    # Published-only observability features; kept separate from ``features`` so no
    # dimension, evidence, or diagnosis consumer reads them.
    supplementary: dict = dataclasses.field(default_factory=dict)

    def records(self) -> list:
        return list(self.features.values())


def _ratio(numerator, denominator):
    if numerator is None or denominator is None:
        return None
    if denominator <= 0:
        return None
    return numerator / denominator


def _artifacts(inputs, metric_ids):
    artifacts = []
    for metric_id in metric_ids:
        record = inputs.metrics.get(metric_id)
        if record is None:
            continue
        artifacts.append(
            SourceArtifact(
                metric=metric_id,
                path=inputs.source_path(metric_id),
                selector=f"/metrics[id={metric_id}]/value",
            )
        )
    return artifacts


def _record(
    bundle_features,
    inputs,
    feature_id,
    value,
    state,
    interpretation="",
    compatibility=None,
    input_metric_ids=None,
):
    metric_ids = (
        input_metric_ids or feature_registry.FEATURE_REGISTRY[feature_id]["input_metric_ids"]
    )
    bundle_features[feature_id] = feature_registry.make_record(
        feature_id,
        value,
        state,
        _artifacts(inputs, metric_ids),
        interpretation=interpretation,
        compatibility=compatibility,
        input_metric_ids=metric_ids,
    )


def _inflation_state(value):
    if value is None:
        return "UNKNOWN"
    if value <= TAU_I_PREF:
        return "PASS"
    if value < TAU_I_FAIL:
        return "WATCH"
    return "FAIL"


def compute_features(inputs) -> FeatureBundle:
    from chipcompiler.analysis.qor.compatibility import evaluate_route_compatibility

    f: dict = {}

    leak = inputs.value("synthesis_power_leakage_uw")
    dynamic = inputs.value("synthesis_power_dynamic_uw")
    leak_frac = _ratio(leak, dynamic + leak if dynamic is not None and leak is not None else None)
    _record(
        f,
        inputs,
        "F_SYN_LEAK_FRAC",
        leak_frac,
        "PASS" if leak_frac is not None else "UNKNOWN",
        "Static leakage share of synthesized netlist power.",
    )

    power_metric_ids = ("power_analysis_dynamic_uw", "power_analysis_leakage_uw")
    power_records = [inputs.metrics.get(metric_id) for metric_id in power_metric_ids]
    if all(record is not None and record.step == "power_analysis" for record in power_records):
        dynamic, leak = (record.value for record in power_records)
        power_leak_frac = _ratio(leak, dynamic + leak)
    else:
        power_metric_ids = None
        power_leak_frac = None
    _record(
        f,
        inputs,
        "F_PWR_LEAK_FRAC",
        power_leak_frac,
        "PASS" if power_leak_frac is not None else "UNKNOWN",
        "Static leakage share of signoff power analysis.",
        input_metric_ids=power_metric_ids,
    )

    cell_area = inputs.value("synthesis_cell_area")
    core_area = inputs.value("core_area")
    plan_density = _ratio(cell_area, core_area)
    _record(
        f,
        inputs,
        "F_PLAN_DENSITY",
        plan_density,
        "PASS" if plan_density is not None else "UNKNOWN",
        "Early floorplanning feasibility indicator; not placement utilization.",
    )

    i_place = _ratio(inputs.value("place_grwl"), inputs.value("place_hpwl"))
    _record(
        f,
        inputs,
        "F_PL_I_PLACE",
        i_place,
        _inflation_state(i_place),
        "Global-routing realization overhead relative to the HPWL baseline.",
    )

    cong_total = inputs.value("place_congestion_egr_overflow_total")
    cong_conc = _ratio(inputs.value("place_congestion_egr_overflow_max"), cong_total)
    _record(
        f,
        inputs,
        "F_PL_CONG_CONC",
        cong_conc,
        "PASS" if cong_conc is not None else "UNKNOWN",
        "Spatial congestion localization (peak bin share of total overflow).",
    )

    b_max = inputs.value("clock_path_max_buffer")
    b_min = inputs.value("clock_path_min_buffer")
    imbalance = None
    if b_max is not None and b_max >= 1 and b_min is not None and b_min <= b_max:
        imbalance = (b_max - b_min) / b_max
    _record(
        f,
        inputs,
        "F_CTS_BUF_IMBAL",
        imbalance,
        (
            "PASS"
            if imbalance is not None and imbalance < ROBUSTNESS_CONTRIBUTOR_WATCH
            else "WATCH"
            if imbalance is not None
            else "UNKNOWN"
        ),
        "Structural clock sink path depth asymmetry; hold risk proxy.",
    )

    compatibility = evaluate_route_compatibility(cts_transformed=_cts_transformed(inputs))
    route_wl = inputs.value("route_wirelength")
    i_route = None
    i_total = None
    route_note = ""
    if compatibility.status == EXACT_COMPATIBLE:
        i_route = _ratio(route_wl, inputs.value("place_grwl"))
        i_total = _ratio(route_wl, inputs.value("place_hpwl"))
    else:
        route_note = "Route side INCOMPATIBLE; ratios evaluate strictly to UNKNOWN."

    _record(
        f,
        inputs,
        "F_RT_I_ROUTE",
        i_route,
        _inflation_state(i_route) if route_wl is not None else "UNKNOWN",
        "Detailed-routing inflation relative to global routing." + route_note,
        compatibility=compatibility.to_contract(),
    )
    _record(
        f,
        inputs,
        "F_RT_I_TOTAL",
        i_total,
        _inflation_state(i_total) if route_wl is not None else "UNKNOWN",
        "Total realized interconnect inflation over the HPWL baseline." + route_note,
        compatibility=compatibility.to_contract(),
    )

    via_density = _ratio(inputs.value("route_via_count"), route_wl)
    _record(
        f,
        inputs,
        "F_RT_VIA_DENSITY",
        via_density,
        "PASS" if via_density is not None else "UNKNOWN",
        "Cut via count per routed micron; manufacturing complexity proxy.",
    )

    coupling = _ratio(
        inputs.value("rcx_worst_coupling_capacitance_ff"),
        inputs.value("rcx_worst_total_capacitance_ff"),
    )
    _record(
        f,
        inputs,
        "F_RCX_CPL_FRAC",
        coupling,
        "PASS" if coupling is not None else "UNKNOWN",
        "Parasitic lateral coupling share; crosstalk susceptibility indicator.",
    )

    congestion = None
    severity_terms = []
    rudy = inputs.value("place_rudy_utilization_max")
    lut_rudy = inputs.value("place_lutrudy_utilization_max")
    egr_max = inputs.value("place_congestion_egr_overflow_max")
    egr_total = inputs.value("place_congestion_egr_overflow_total")
    if rudy is not None:
        severity_terms.append(rudy / TAU_RUDY_FAIL)
    if lut_rudy is not None:
        severity_terms.append(lut_rudy / TAU_RUDY_FAIL)
    if egr_max is not None:
        severity_terms.append(egr_max / TAU_EGR_MAX_FAIL)
    if egr_total is not None:
        severity_terms.append(egr_total / TAU_EGR_TOTAL_FAIL)
    if severity_terms:
        congestion = max(severity_terms)

    tclk = inputs.tclk_ns
    ws = inputs.value("sta_setup_wns")
    headroom = _ratio(ws, tclk) if tclk else None
    _record(
        f,
        inputs,
        "F_STA_HEADROOM",
        headroom,
        _headroom_state(ws, tclk),
        "Normalized signed setup slack headroom.",
    )

    frequency_margin = None
    if ws is not None and tclk and tclk - ws > 0:
        target_frequency = 1000.0 / tclk
        achieved_frequency = 1000.0 / (tclk - ws)
        frequency_margin = (achieved_frequency - target_frequency) / target_frequency
    _record(
        f,
        inputs,
        "F_STA_FREQ_MARGIN",
        frequency_margin,
        "OPPORTUNITY" if frequency_margin is not None and frequency_margin >= 0 else "UNKNOWN",
        "Derived frequency margin relative to the target clock period.",
    )

    setup_ws_values = [corner.setup_ws for corner in inputs.corners]
    hold_ws_values = [corner.hold_ws for corner in inputs.corners if corner.hold_ws is not None]
    delta_setup = max(setup_ws_values) - min(setup_ws_values) if setup_ws_values else None
    delta_hold = max(hold_ws_values) - min(hold_ws_values) if len(hold_ws_values) >= 2 else None
    pvt_setup = _ratio(delta_setup, tclk) if tclk else None
    pvt_hold = _ratio(delta_hold, tclk) if tclk else None
    pvt_values = [value for value in (pvt_setup, pvt_hold) if value is not None]
    pvt_max: float | None = max(pvt_values) if pvt_values else None
    _record(
        f,
        inputs,
        "F_STA_PVT_SETUP_DISP",
        pvt_setup,
        "PASS" if pvt_setup is not None else "UNKNOWN",
        "Setup timing sensitivity to multi-corner PVT variations.",
    )
    _record(
        f,
        inputs,
        "F_STA_PVT_HOLD_DISP",
        pvt_hold,
        "PASS" if pvt_hold is not None else "UNKNOWN",
        "Hold timing sensitivity to multi-corner PVT variations.",
    )
    _record(
        f,
        inputs,
        "F_STA_PVT_MAX_DISP",
        pvt_max,
        "PASS" if pvt_max is not None else "UNKNOWN",
        "Maximum combined timing sensitivity across PVT corners.",
    )

    return FeatureBundle(
        features=f,
        supplementary=_supplementary_features(inputs),
        i_place=i_place,
        i_route=i_route,
        i_total=i_total,
        congestion_severity=congestion,
        cts_imbalance=imbalance,
        pvt_setup_disp=pvt_setup,
        pvt_hold_disp=pvt_hold,
        compatibility=compatibility,
    )


def _add_supplementary_feature(
    out: dict,
    inputs,
    feature_id: str,
    value,
    state: str,
    interpretation: str,
    artifacts: list | None = None,
) -> None:
    entry = feature_registry.SUPPLEMENTARY_FEATURE_REGISTRY[feature_id]
    metric_ids = list(entry["input_metric_ids"])
    resolved_state = state if value is not None else "UNKNOWN"
    out[feature_id] = feature_registry.make_record(
        feature_id,
        value,
        resolved_state,
        _artifacts(inputs, metric_ids) if artifacts is None else artifacts,
        interpretation=interpretation,
        input_metric_ids=metric_ids,
    )


def _slack_feature_state(value) -> str:
    return "PASS" if value is not None and value >= 0 else "FAIL"


def _supplementary_features(inputs) -> dict:
    """Features published in the report for observability without changing scores or gates."""
    out: dict = {}
    total, overflowed = inputs.egr_gcell_count, inputs.egr_overflowed_gcell_count
    fraction = _ratio(overflowed, total)
    artifacts = []
    if fraction is not None and inputs.egr_grid_source_path:
        artifacts = [
            SourceArtifact(
                metric="place_congestion_egr_overflow_total",
                path=inputs.egr_grid_source_path,
                selector="/grid[overflow>0]/count/grid/count",
            )
        ]
    _add_supplementary_feature(
        out,
        inputs,
        "F_PL_EGR_OVERFLOW_GCELL_FRAC",
        fraction,
        "PASS",
        "Share of global-route GCells with overflow; size-normalized congestion indicator.",
        artifacts=artifacts,
    )

    tclk = inputs.tclk_ns
    setup_tns = inputs.value("sta_setup_tns")
    hold_tns = inputs.value("sta_hold_tns")
    _add_supplementary_feature(
        out,
        inputs,
        "F_STA_SETUP_TNS",
        setup_tns,
        _slack_feature_state(setup_tns),
        "Signed setup total negative slack (ns).",
    )
    _add_supplementary_feature(
        out,
        inputs,
        "F_STA_HOLD_TNS",
        hold_tns,
        _slack_feature_state(hold_tns),
        "Signed hold total negative slack (ns).",
    )
    tns_norm = setup_tns / tclk if setup_tns is not None and tclk and tclk > 0 else None
    _add_supplementary_feature(
        out,
        inputs,
        "F_STA_SETUP_TNS_NORM",
        tns_norm,
        _slack_feature_state(tns_norm),
        "Setup TNS in clock periods; comparable across designs and clock targets.",
    )
    for feature_id, metric_id, label in (
        ("F_STA_SETUP_FEP", "sta_setup_violation_count", "setup"),
        ("F_STA_HOLD_FEP", "sta_hold_violation_count", "hold"),
    ):
        count = inputs.value(metric_id)
        _add_supplementary_feature(
            out,
            inputs,
            feature_id,
            count,
            "PASS" if count == 0 else "FAIL",
            f"Failing {label} endpoint count; the endpoint population is not "
            "emitted, so no fraction is derived.",
        )
    hold_ws = inputs.value("sta_hold_wns")
    hold_headroom = _ratio(hold_ws, tclk) if tclk and hold_ws is not None else None
    _add_supplementary_feature(
        out,
        inputs,
        "F_STA_HOLD_HEADROOM",
        hold_headroom,
        _slack_feature_state(hold_headroom),
        "Signed worst hold slack in clock periods.",
    )
    return out


def _headroom_state(ws, tclk):
    if ws is None or not tclk:
        return "UNKNOWN"
    from chipcompiler.analysis.qor.calibration import (
        GUARDBAND_FRACTION,
        OVER_PROVISION_FRACTION,
    )

    guardband = GUARDBAND_FRACTION * tclk
    over_provision = OVER_PROVISION_FRACTION * tclk
    if ws < 0:
        return "FAIL"
    if ws < guardband:
        return "WATCH"
    if ws > over_provision:
        return "OPPORTUNITY"
    return "PASS"


def _cts_transformed(inputs) -> bool:
    """True when CTS ran and its buffer population is present or unknown.

    A completed CTS step inserts clock-tree nets; only an explicitly
    measured zero buffer/inverter population (CTS step succeeded with a
    counted empty insertion, e.g. no clock or direct conversion) keeps
    the identity mapping.
    """
    if inputs.step_state("cts") != "Success":
        return False
    buffers = inputs.value("cts_buffer_count")
    inverters = inputs.value("cts_inverter_count")
    if buffers is None or inverters is None:
        return True
    return buffers + inverters > 0
