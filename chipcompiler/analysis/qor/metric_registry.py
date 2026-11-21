"""Canonical registry of metric ids consumed by the QoR engine.

The step emitters (``tools/ecc/metrics.py``) own extraction and keep
emitting schema-v3 ``qor_metrics.json`` unchanged; this registry is the
single place that declares which canonical ids the engine reads, their
units, and their polarities.

Naming note (spec §2.3): the legacy emitter id ``sta_setup_wns`` carries
the *signed worst setup slack* across corners (never clamped). The
engine exposes it as signed ``WS`` and derives the clamped ``WNS =
min(0, WS)`` for gating; the legacy id stays the wire name for
compatibility with already-published artifacts.
"""

# metric id -> (unit, polarity)
METRIC_REGISTRY = {
    "synthesis_cell_area": ("um^2", "lower_is_better"),
    "synthesis_cell_count": ("count", "trend_only"),
    "synthesis_wire_count": ("count", "trend_only"),
    "synthesis_power_dynamic_uw": ("uW", "lower_is_better"),
    "synthesis_power_leakage_uw": ("uW", "lower_is_better"),
    "power_analysis_dynamic_uw": ("uW", "lower_is_better"),
    "power_analysis_leakage_uw": ("uW", "lower_is_better"),
    "die_area": ("um^2", "lower_is_better"),
    "core_area": ("um^2", "lower_is_better"),
    "core_utilization": ("ratio", "target_range"),
    "place_hpwl": ("um", "lower_is_better"),
    "place_grwl": ("um", "lower_is_better"),
    "place_flute_wirelength": ("um", "lower_is_better"),
    "place_congestion_egr_overflow_max": ("count", "lower_is_better"),
    "place_congestion_egr_overflow_total": ("count", "lower_is_better"),
    "place_rudy_utilization_max": ("ratio", "lower_is_better"),
    "place_lutrudy_utilization_max": ("ratio", "lower_is_better"),
    "cts_buffer_count": ("count", "lower_is_better"),
    "cts_inverter_count": ("count", "lower_is_better"),
    "clock_path_max_buffer": ("count", "lower_is_better"),
    "clock_path_min_buffer": ("count", "trend_only"),
    "clock_wirelength": ("um", "lower_is_better"),
    "route_wirelength": ("um", "lower_is_better"),
    "route_via_count": ("count", "lower_is_better"),
    "rcx_spef_file_count": ("count", "trend_only"),
    "rcx_expected_corner_count": ("count", "trend_only"),
    "rcx_missing_corner_count": ("count", "lower_is_better"),
    "rcx_spef_parse_failure_count": ("count", "lower_is_better"),
    "rcx_worst_total_capacitance_ff": ("fF", "lower_is_better"),
    "rcx_worst_coupling_capacitance_ff": ("fF", "lower_is_better"),
    "drc_count": ("count", "lower_is_better"),
    "lvs_count": ("count", "lower_is_better"),
    "antenna_violation_count": ("count", "lower_is_better"),
    "antenna_signal_net_count": ("count", "trend_only"),
    "antenna_gate_pin_count": ("count", "trend_only"),
    "harden_artifact_missing_count": ("count", "lower_is_better"),
    "sta_setup_wns": ("ns", "higher_is_better"),
    "sta_setup_tns": ("ns", "higher_is_better"),
    "sta_hold_wns": ("ns", "higher_is_better"),
    "sta_hold_tns": ("ns", "higher_is_better"),
    "sta_frequency_mhz": ("MHz", "higher_is_better"),
    "sta_setup_violation_count": ("count", "lower_is_better"),
    "sta_hold_violation_count": ("count", "lower_is_better"),
    "sta_max_transition_violation_count": ("count", "lower_is_better"),
    "sta_max_capacitance_violation_count": ("count", "lower_is_better"),
    "sta_max_fanout_violation_count": ("count", "lower_is_better"),
    "sta_corner_count": ("count", "trend_only"),
    "sta_expected_corner_count": ("count", "trend_only"),
    "sta_missing_corner_count": ("count", "lower_is_better"),
    "sta_worst_setup_corner": ("", "trend_only"),
}

# Optional physical validity ranges: metric id -> (low, high, low_inclusive).
# ``None`` means unbounded. Values outside the range are physically impossible
# (e.g. a percentage reported as a ratio) and are treated as UNKNOWN by the
# loader instead of being scored. Ids absent here are only checked for being
# finite. Signed ids (slacks) and ``place_rudy_utilization_max`` (may exceed
# 1.0 when congested) are deliberately not capped.
_NON_NEGATIVE = (0.0, None, True)
METRIC_VALID_RANGE = {
    "core_utilization": (0.0, 1.0, False),
    "place_rudy_utilization_max": _NON_NEGATIVE,
    "place_lutrudy_utilization_max": _NON_NEGATIVE,
    "sta_frequency_mhz": (0.0, None, False),
    **{
        metric_id: _NON_NEGATIVE
        for metric_id, (unit, _direction) in METRIC_REGISTRY.items()
        if unit in ("um^2", "um", "count", "uW", "fF")
    },
}


def metric_range_violation(metric_id, value):
    """Return a short reason when ``value`` is outside the id's valid range."""
    bounds = METRIC_VALID_RANGE.get(metric_id)
    if bounds is None:
        return None
    low, high, low_inclusive = bounds
    if low is not None and (value < low or (value == low and not low_inclusive)):
        return f"must be {'>=' if low_inclusive else '>'} {low:g}"
    if high is not None and value > high:
        return f"must be <= {high:g}"
    return None


# Steps whose Success state and analysis payload the engine consumes.
SCORED_STEP_VALUES = (
    "synthesis",
    "post_floorplan",
    "placement",
    "cts",
    "legalization",
    "routing",
    "drc",
    "lvs",
    "antenna_check",
    "rcx",
    "sta",
    "power_analysis",
    "harden",
)


def clamped_wns(ws_ns):
    """WNS = min(0, WS); gating-only, never a continuous quality input."""
    if ws_ns is None:
        return None
    return min(0.0, ws_ns)
