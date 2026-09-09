"""Shared fixtures for the QoR engine tests."""

from chipcompiler.analysis.qor.loader import CornerSlack, MetricRecord, QorInputs

SUCCESS = "Success"


def make_metric(metric_id, value, step="sta", role="final", unit="", corner=None):
    return MetricRecord(
        metric_id=metric_id,
        value=value,
        unit=unit,
        step=step,
        project_role=role,
        corner=corner,
        source={"kind": "analysis", "path": f"{step}_ecc/analysis/qor_metrics.json"},
    )


def make_inputs(metrics=None, flow_states=None, **overrides) -> QorInputs:
    metrics = metrics or {}

    def _value(metric_id):
        return metrics[metric_id].value if metric_id in metrics else None

    derived = {
        # Mirror the loader: corner/SPEF counts come from payload metrics.
        "sta_expected_corners": _value("sta_expected_corner_count"),
        "rcx_spef_count": _value("rcx_spef_file_count"),
        "rcx_expected_spef": _value("rcx_expected_corner_count"),
    }
    derived.update(overrides)
    inputs = QorInputs(
        design="gcd",
        workspace_path="/tmp/ws",
        flow_states=flow_states if flow_states is not None else _all_success(),
        metrics=metrics,
    )
    for key, value in derived.items():
        setattr(inputs, key, value)
    return inputs


def _all_success():
    return {
        step: SUCCESS
        for step in (
            "Synthesis",
            "Floorplan",
            "place",
            "CTS",
            "route",
            "drc",
            "lvs",
            "RCX",
            "sta",
            "Harden",
        )
    }


def gcd_metrics() -> dict:
    """Reference GCD fixture inputs (spec §12.1)."""
    records = [
        make_metric("synthesis_cell_area", 800.0, step="Synthesis"),
        make_metric("core_area", 1538.46, step="Floorplan"),
        make_metric("core_utilization", 0.52, step="Floorplan"),
        make_metric("place_hpwl", 3143.52, step="place"),
        make_metric("place_grwl", 3812.00, step="place"),
        make_metric("place_rudy_utilization_max", 0.0, step="place"),
        make_metric("cts_buffer_count", 4, step="CTS"),
        make_metric("cts_inverter_count", 0, step="CTS"),
        make_metric("clock_path_max_buffer", 4, step="CTS"),
        make_metric("clock_path_min_buffer", 4, step="CTS"),
        make_metric("clock_wirelength", 610.0, step="CTS"),
        make_metric("route_wirelength", 4315.53, step="route"),
        make_metric("route_via_count", 608, step="route"),
        make_metric("drc_count", 0, step="drc"),
        make_metric("lvs_count", 0, step="lvs"),
        make_metric("rcx_spef_file_count", 2, step="RCX"),
        make_metric("rcx_expected_corner_count", 2, step="RCX"),
        make_metric("rcx_missing_corner_count", 0, step="RCX"),
        make_metric("rcx_worst_total_capacitance_ff", 120.0, step="RCX"),
        make_metric("rcx_worst_coupling_capacitance_ff", 30.0, step="RCX"),
        make_metric("sta_setup_wns", 16.622, step="sta"),
        make_metric("sta_setup_tns", 0.0, step="sta"),
        make_metric("sta_hold_wns", 0.1, step="sta"),
        make_metric("sta_hold_tns", 0.0, step="sta"),
        make_metric("sta_setup_violation_count", 0, step="sta"),
        make_metric("sta_hold_violation_count", 0, step="sta"),
        make_metric("sta_expected_corner_count", 2, step="sta"),
        make_metric("sta_missing_corner_count", 0, step="sta"),
        make_metric("sta_worst_setup_corner", "MAX_125", step="sta"),
        make_metric("harden_artifact_missing_count", 0, step="Harden"),
    ]
    return {record.metric_id: record for record in records}


def gcd_corners():
    """Two corners reproducing the spec §12.1 dispersions.

    WS spread: 18.980 - 16.622 = 2.358 ns; hold spread: 0.274 - 0.100 = 0.174 ns.
    """
    return [
        CornerSlack(corner="MAX_125", setup_ws=16.622, hold_ws=0.100, setup_nvp=0, hold_nvp=0),
        CornerSlack(corner="MAX_M40", setup_ws=18.980, hold_ws=0.274, setup_nvp=0, hold_nvp=0),
    ]
