"""Canonical registry of derived features (spec §5, §6).

Epistemic classification strings come from the spec's seven tiers; they
are audit metadata attached to every feature record, not code structure.
"""


def _feature(formula, classification, semantic_class, inputs, unit="ratio"):
    return {
        "formula": formula,
        "classification": classification,
        "semantic_class": semantic_class,
        "input_metric_ids": inputs,
        "unit": unit,
    }


FEATURE_REGISTRY = {
    "F_SYN_LEAK_FRAC": _feature(
        "synthesis_power_leakage_uw / (synthesis_power_dynamic_uw + synthesis_power_leakage_uw)",
        "EXACT_TRANSFORMATION",
        "composition_fraction",
        ["synthesis_power_dynamic_uw", "synthesis_power_leakage_uw"],
    ),
    "F_PWR_LEAK_FRAC": _feature(
        "power_analysis_leakage_uw / (power_analysis_dynamic_uw + power_analysis_leakage_uw)",
        "EXACT_TRANSFORMATION",
        "composition_fraction",
        ["power_analysis_dynamic_uw", "power_analysis_leakage_uw"],
    ),
    "F_PLAN_DENSITY": _feature(
        "synthesis_cell_area / core_area",
        "DERIVED_ENGINEERING_FEATURE",
        "planning_density_ratio",
        ["synthesis_cell_area", "core_area"],
    ),
    "F_PL_I_PLACE": _feature(
        "place_grwl / place_hpwl",
        "DERIVED_ENGINEERING_FEATURE",
        "bound_proximity",
        ["place_grwl", "place_hpwl"],
    ),
    "F_PL_CONG_CONC": _feature(
        "place_congestion_egr_overflow_max / place_congestion_egr_overflow_total",
        "DERIVED_ENGINEERING_FEATURE",
        "spatial_concentration",
        ["place_congestion_egr_overflow_max", "place_congestion_egr_overflow_total"],
    ),
    "F_CTS_BUF_IMBAL": _feature(
        "(clock_path_max_buffer - clock_path_min_buffer) / clock_path_max_buffer",
        "DERIVED_ENGINEERING_FEATURE",
        "structural_asymmetry",
        ["clock_path_max_buffer", "clock_path_min_buffer"],
    ),
    "F_RT_I_ROUTE": _feature(
        "route_wirelength / place_grwl",
        "DERIVED_ENGINEERING_FEATURE",
        "bound_proximity",
        ["route_wirelength", "place_grwl"],
    ),
    "F_RT_I_TOTAL": _feature(
        "route_wirelength / place_hpwl",
        "DERIVED_ENGINEERING_FEATURE",
        "bound_proximity",
        ["route_wirelength", "place_hpwl"],
    ),
    "F_RT_VIA_DENSITY": _feature(
        "route_via_count / route_wirelength",
        "DERIVED_ENGINEERING_FEATURE",
        "manufacturing_complexity_proxy",
        ["route_via_count", "route_wirelength"],
    ),
    "F_RCX_CPL_FRAC": _feature(
        "rcx_worst_coupling_capacitance_ff / rcx_worst_total_capacitance_ff",
        "DERIVED_ENGINEERING_FEATURE",
        "crosstalk_susceptibility",
        ["rcx_worst_coupling_capacitance_ff", "rcx_worst_total_capacitance_ff"],
    ),
    "F_STA_HEADROOM": _feature(
        "sta_setup_ws_ns / Tclk",
        "DERIVED_ENGINEERING_FEATURE",
        "normalized_headroom",
        ["sta_setup_wns"],
    ),
    "F_STA_FREQ_MARGIN": _feature(
        "(1000 / (Tclk - sta_setup_ws_ns) - Ftarget) / Ftarget",
        "DERIVED_ENGINEERING_FEATURE",
        "frequency_margin",
        ["sta_setup_wns"],
    ),
    "F_STA_PVT_SETUP_DISP": _feature(
        "(max_c WSsetup_c - min_c WSsetup_c) / Tclk",
        "EMPIRICAL_STATISTICAL_FEATURE",
        "corner_dispersion",
        ["sta_setup_wns"],
    ),
    "F_STA_PVT_HOLD_DISP": _feature(
        "(max_c WShold_c - min_c WShold_c) / Tclk",
        "EMPIRICAL_STATISTICAL_FEATURE",
        "corner_dispersion",
        ["sta_hold_wns"],
    ),
    "F_STA_PVT_MAX_DISP": _feature(
        "max(delta_setup, delta_hold) / Tclk",
        "EMPIRICAL_STATISTICAL_FEATURE",
        "corner_dispersion",
        ["sta_setup_wns", "sta_hold_wns"],
    ),
    "S_CONG": _feature(
        "max(RUDYmax/tau_rudy, EGRmax/tau_egr_max, EGRtotal/tau_egr_total)",
        "CALIBRATED_HEURISTIC",
        "congestion_severity_index",
        [
            "place_rudy_utilization_max",
            "place_congestion_egr_overflow_max",
            "place_congestion_egr_overflow_total",
        ],
    ),
}

# Published-only observability features (report ``supplementary_features``).
# They are never read by dimension scoring, gating, evidence, or diagnosis,
# so adding or computing them cannot change existing scores.
SUPPLEMENTARY_FEATURE_REGISTRY = {
    "F_PL_EGR_OVERFLOW_GCELL_FRAC": _feature(
        "count(GCells with union overflow > 0) / count(GCells) from the placement EGR map",
        "DERIVED_ENGINEERING_FEATURE",
        "egr_overflow_gcell_fraction",
        ["place_congestion_egr_overflow_total"],
    ),
    "F_STA_SETUP_TNS": _feature(
        "sta_setup_tns",
        "EXACT_TRANSFORMATION",
        "total_negative_slack",
        ["sta_setup_tns"],
        unit="ns",
    ),
    "F_STA_HOLD_TNS": _feature(
        "sta_hold_tns",
        "EXACT_TRANSFORMATION",
        "total_negative_slack",
        ["sta_hold_tns"],
        unit="ns",
    ),
    "F_STA_SETUP_TNS_NORM": _feature(
        "sta_setup_tns / Tclk",
        "DERIVED_ENGINEERING_FEATURE",
        "normalized_total_negative_slack",
        ["sta_setup_tns"],
    ),
    "F_STA_SETUP_FEP": _feature(
        "sta_setup_violation_count",
        "EXACT_TRANSFORMATION",
        "failing_endpoint_count",
        ["sta_setup_violation_count"],
        unit="count",
    ),
    "F_STA_HOLD_FEP": _feature(
        "sta_hold_violation_count",
        "EXACT_TRANSFORMATION",
        "failing_endpoint_count",
        ["sta_hold_violation_count"],
        unit="count",
    ),
    "F_STA_HOLD_HEADROOM": _feature(
        "sta_hold_wns_ns / Tclk",
        "DERIVED_ENGINEERING_FEATURE",
        "normalized_hold_margin",
        ["sta_hold_wns"],
    ),
}


def make_record(
    feature_id,
    value,
    state,
    artifacts,
    interpretation="",
    compatibility=None,
    input_metric_ids=None,
):
    """Build a FeatureRecord from the registry entry."""
    from chipcompiler.analysis.qor.models import FeatureRecord

    entry = FEATURE_REGISTRY.get(feature_id) or SUPPLEMENTARY_FEATURE_REGISTRY[feature_id]
    return FeatureRecord(
        feature_id=feature_id,
        value=value,
        unit=entry["unit"],
        formula=entry["formula"],
        classification=entry["classification"],
        semantic_class=entry["semantic_class"],
        state=state,
        input_metric_ids=list(input_metric_ids or entry["input_metric_ids"]),
        input_source_artifacts=artifacts,
        interpretation=interpretation,
        compatibility=compatibility,
    )
