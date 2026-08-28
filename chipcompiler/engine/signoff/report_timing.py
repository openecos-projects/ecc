"""Timing-chain extraction for the design-summary report.

Corner assembly, top-level slack rollup, target resolution, and the
timing/clock families. Kept together because the top-level slacks roll up
from the multi-corner records and the derived fmax / critical-path rules
depend on that rollup.
"""

from chipcompiler.engine.signoff.report_data import (
    ClockMetrics,
    CornerTimingRecord,
    TimingMetrics,
)
from chipcompiler.engine.signoff.report_extract import (
    _is_record,
    _parse_corner_attributes,
    _parse_number,
)


def _extract_corner_records(store, inputs) -> list[CornerTimingRecord]:
    """Merge STA corner payloads from stage stores and corner reports."""
    merged_corners: dict[str, dict] = {}
    corner_sources = []
    for stage_name in ("STA", "sta_ecc", "Synth"):
        stage_data = store.stage(stage_name)
        corners = stage_data.get("corners") if _is_record(stage_data) else None
        if _is_record(corners):
            corner_sources.append(corners)
    if _is_record(inputs.get("sta_corner_reports")):
        corner_sources.append(inputs["sta_corner_reports"])
    for source in corner_sources:
        for corner_name, corner_data in source.items():
            if _is_record(corner_data):
                merged_corners.setdefault(corner_name, {}).update(corner_data)

    records = []
    for corner_name, corner_data in merged_corners.items():
        process, temperature, voltage, rc_corner = _parse_corner_attributes(corner_name)
        setup_obj = corner_data.get("setup") if _is_record(corner_data.get("setup")) else {}
        hold_obj = corner_data.get("hold") if _is_record(corner_data.get("hold")) else {}
        summary_obj = corner_data.get("summary") if _is_record(corner_data.get("summary")) else {}
        summary_setup = summary_obj.get("setup") if _is_record(summary_obj.get("setup")) else {}
        summary_hold = summary_obj.get("hold") if _is_record(summary_obj.get("hold")) else {}

        def pick(*candidates):
            for candidate in candidates:
                number = _parse_number(candidate)
                if number is not None:
                    return number
            return None

        corner_setup_wns = pick(
            corner_data.get("setup_wns"),
            corner_data.get("wns"),
            setup_obj.get("wns"),
            summary_setup.get("wns"),
        )
        corner_hold_wns = pick(
            corner_data.get("hold_wns"), hold_obj.get("wns"), summary_hold.get("wns")
        )
        passed = (corner_setup_wns is None or corner_setup_wns >= 0) and (
            corner_hold_wns is None or corner_hold_wns >= 0
        )
        records.append(
            CornerTimingRecord(
                corner=corner_name,
                process_corner=(
                    corner_data.get("process")
                    if isinstance(corner_data.get("process"), str)
                    else process
                ),
                voltage_v=pick(corner_data.get("voltage"), corner_data.get("voltage_v"), voltage),
                temperature_c=pick(
                    corner_data.get("temperature"), corner_data.get("temperature_c"), temperature
                ),
                rc_corner=(
                    corner_data.get("rc") if isinstance(corner_data.get("rc"), str) else rc_corner
                ),
                setup_wns_ns=corner_setup_wns,
                setup_tns_ns=pick(
                    corner_data.get("setup_tns"),
                    corner_data.get("tns"),
                    setup_obj.get("tns"),
                    summary_setup.get("tns"),
                ),
                hold_wns_ns=corner_hold_wns,
                hold_tns_ns=pick(
                    corner_data.get("hold_tns"), hold_obj.get("tns"), summary_hold.get("tns")
                ),
                violating_endpoints_setup=pick(
                    corner_data.get("violating_endpoints_setup"),
                    setup_obj.get("nvp"),
                    summary_setup.get("nvp"),
                ),
                violating_endpoints_hold=pick(
                    corner_data.get("violating_endpoints_hold"),
                    hold_obj.get("nvp"),
                    summary_hold.get("nvp"),
                ),
                status="pass" if passed else "fail",
            )
        )
    return records


def _rollup_from_corners(corners, values: dict) -> None:
    """Fill missing top-level timing slack from the multi-corner records."""
    if not corners:
        return
    for key, attr in (
        ("setup_wns_ns", "setup_wns_ns"),
        ("setup_tns_ns", "setup_tns_ns"),
        ("hold_wns_ns", "hold_wns_ns"),
        ("hold_tns_ns", "hold_tns_ns"),
    ):
        if values.get(key) is None:
            valid = [
                getattr(corner, attr) for corner in corners if getattr(corner, attr) is not None
            ]
            values[key] = min(valid) if valid else None
    if values.get("violating_endpoints_setup") is None:
        values["violating_endpoints_setup"] = float(
            sum(corner.violating_endpoints_setup or 0 for corner in corners)
        )
    if values.get("violating_endpoints_hold") is None:
        values["violating_endpoints_hold"] = float(
            sum(corner.violating_endpoints_hold or 0 for corner in corners)
        )


def _timing_targets(q, inputs):
    """Resolve the target clock period / frequency pair."""
    period_value = q(
        "Timing",
        "Target Clock Period",
        ["STA", "CTS", "Route", "Place", "Synth", "Parameters", "Home"],
        [
            "clock_period",
            "CLOCK_PERIOD",
            "target_clock_period",
            "target_clock_period_ns",
            "clockPeriod",
            "target_period",
            "PERIOD",
            "period",
            "SDC_CLOCK_PERIOD",
            "sdc_clock_period",
            "summary.clock_period",
            "summary.setup.clock_period",
            "summary.target_clock_period",
        ],
    )[0]
    if period_value is not None and period_value > 0:
        return period_value, round(1000 / period_value, 2)
    freq_value = q(
        "Timing",
        "Target Frequency",
        ["STA", "Parameters", "Home", "Synth"],
        [
            "Frequency max [MHz]",
            "Frequency max",
            "Frequency [MHz]",
            "Frequency",
            "frequency_max_mhz",
            "frequency_max",
            "CLOCK_FREQ_MHZ",
            "target_frequency_mhz",
            "clock_frequency_mhz",
            "target_frequency",
            "frequencyTarget",
            "FREQUENCY",
            "frequency",
        ],
    )[0]
    frequency_target = inputs.get("frequency_target")
    if freq_value is not None and freq_value > 0:
        return round(1000 / freq_value, 3), freq_value
    if isinstance(frequency_target, (int, float)) and frequency_target > 0:
        return round(1000 / frequency_target, 3), float(frequency_target)
    return None, None


def _extract_timing(q, inputs, corners) -> TimingMetrics:
    target_clock_period_ns, target_frequency_mhz = _timing_targets(q, inputs)

    values = {
        "setup_wns_ns": q(
            "Timing",
            "Setup WNS",
            ["STA", "Route", "CTS", "Place", "Synth"],
            [
                "sta_setup_wns",
                "setup_wns",
                "setup.wns",
                "summary.setup.wns",
                "summary.wns",
                "worst_negative_slack_setup",
                "worst_negative_slack",
                "worstSetup.wns",
                "wns",
            ],
        )[0],
        "setup_tns_ns": q(
            "Timing",
            "Setup TNS",
            ["STA", "Route", "CTS", "Place", "Synth"],
            [
                "sta_setup_tns",
                "setup_tns",
                "setup.tns",
                "summary.setup.tns",
                "summary.tns",
                "total_negative_slack_setup",
                "total_negative_slack",
                "tns",
            ],
        )[0],
        "hold_wns_ns": q(
            "Timing",
            "Hold WNS",
            ["STA", "Route", "CTS", "Place"],
            [
                "sta_hold_wns",
                "hold_wns",
                "hold.wns",
                "summary.hold.wns",
                "hold_worst_negative_slack",
                "worstHold.wns",
            ],
        )[0],
        "hold_tns_ns": q(
            "Timing",
            "Hold TNS",
            ["STA", "Route", "CTS", "Place"],
            [
                "sta_hold_tns",
                "hold_tns",
                "hold.tns",
                "summary.hold.tns",
                "hold_total_negative_slack",
            ],
        )[0],
        "violating_endpoints_setup": q(
            "Timing",
            "Setup Violating Endpoints",
            ["STA", "Route"],
            [
                "violating_endpoints_setup",
                "setup.nvp",
                "summary.setup.nvp",
                "setup_violating_endpoints",
                "setup_nvp",
                "setupViolationCount",
                "nvp",
            ],
        )[0],
        "violating_endpoints_hold": q(
            "Timing",
            "Hold Violating Endpoints",
            ["STA", "Route"],
            [
                "violating_endpoints_hold",
                "hold.nvp",
                "summary.hold.nvp",
                "hold_violating_endpoints",
                "hold_nvp",
                "holdViolationCount",
            ],
        )[0],
    }
    _rollup_from_corners(corners, values)
    setup_wns_ns = values["setup_wns_ns"]

    fmax_mhz = q(
        "Timing",
        "Achieved Fmax",
        ["STA", "Route", "CTS"],
        [
            "sta_frequency_mhz",
            "frequency_mhz",
            "fmax",
            "achieved_frequency",
            "summary.setup.frequency_mhz",
            "setup.frequency_mhz",
            "summary.frequency_mhz",
        ],
    )[0]
    if fmax_mhz is None:
        if target_clock_period_ns is not None and setup_wns_ns is not None:
            min_period = target_clock_period_ns - setup_wns_ns
            if min_period > 0:
                fmax_mhz = round(1000 / min_period, 2)
        elif target_clock_period_ns is not None:
            fmax_mhz = round(1000 / target_clock_period_ns, 2)

    slew_violations = q(
        "Timing",
        "Max Slew Violations",
        ["STA", "Route", "CTS", "Synth"],
        [
            "slew_violations",
            "max_slew_violations",
            "slew_viols",
            "trans_violations",
            "transition_violations",
            "max_transition_violations",
            "max_slew",
            "slew_violation_count",
            "summary.slew.violations",
            "slew.violations",
            "check_slew",
        ],
    )[0]
    cap_violations = q(
        "Timing",
        "Max Cap Violations",
        ["STA", "Route", "CTS", "Synth"],
        [
            "cap_violations",
            "max_cap_violations",
            "cap_viols",
            "max_cap",
            "capacitance_violations",
            "max_capacitance_violations",
            "cap_violation_count",
            "summary.cap.violations",
            "cap.violations",
            "check_cap",
        ],
    )[0]
    fanout_violations = q(
        "Timing",
        "Max Fanout Violations",
        ["STA", "Route", "Fanout", "CTS", "Synth"],
        [
            "fanout_violations",
            "max_fanout_violations",
            "fanout_viols",
            "fanout_max_violations",
            "max_fanout",
            "fanout_violation_count",
            "summary.fanout.violations",
            "fanout.violations",
            "check_fanout",
        ],
    )[0]
    if setup_wns_ns is not None and setup_wns_ns >= 0:
        slew_violations = 0 if slew_violations is None else slew_violations
        cap_violations = 0 if cap_violations is None else cap_violations
        fanout_violations = 0 if fanout_violations is None else fanout_violations

    critical_path_delay_ns = q(
        "Timing",
        "Critical Path Delay",
        ["STA", "Route", "CTS", "Synth"],
        [
            "critical_path_delay",
            "critical_path_delay_ns",
            "crit_path_delay",
            "data_path_delay",
            "arrival_time",
            "data_arrival_time",
            "path_delay",
            "worst_path_delay",
        ],
    )[0]
    if critical_path_delay_ns is None:
        if target_clock_period_ns is not None and setup_wns_ns is not None:
            derived = target_clock_period_ns - setup_wns_ns
            if derived > 0:
                critical_path_delay_ns = round(derived, 3)
        elif fmax_mhz is not None and fmax_mhz > 0:
            critical_path_delay_ns = round(1000 / fmax_mhz, 3)

    return TimingMetrics(
        target_clock_period_ns=target_clock_period_ns,
        target_frequency_mhz=target_frequency_mhz,
        fmax_mhz=fmax_mhz,
        slew_violations=slew_violations,
        cap_violations=cap_violations,
        fanout_violations=fanout_violations,
        critical_path_delay_ns=critical_path_delay_ns,
        **values,
    )


def _extract_clock(q) -> ClockMetrics:
    skew_value, skew_key, _ = q(
        "Clock",
        "Clock Skew",
        ["CTS", "STA", "Route"],
        [
            "cts_worst_optimized_skew_ns",
            "worst_optimized_skew_ns",
            "cts_worst_skew_ns",
            "worst_skew_ns",
            "clock_skew",
            "skew_ps",
            "skew",
            "max_clock_skew",
            "cts_clock_skew",
            "worst_skew",
        ],
    )
    clock_skew_ps = None
    if skew_value is not None:
        if skew_key.endswith("_ns") or (0 < skew_value < 10.0):
            clock_skew_ps = round(skew_value * 1000, 1)
        else:
            clock_skew_ps = round(skew_value, 1)

    clock_buffer_count = q(
        "Clock",
        "Clock Buffer Count",
        ["CTS", "Route", "Place", "Floor"],
        [
            "cts_buffer_count",
            "CTS.buffer_num",
            "buffer_num",
            "clock_buffer_count",
            "clock_buffers",
            "num_clock_buffers",
        ],
    )[0]
    clock_inverter_count = q(
        "Clock",
        "Clock Inverter Count",
        ["CTS", "Route"],
        ["cts_inverter_count", "clock_inverter_count", "clock_inverters", "num_clock_inverters"],
    )[0]
    clock_cell_count = q(
        "Clock",
        "Clock Cell Count",
        ["CTS", "Route", "Harden"],
        ["Instances.clock.num", "clock_cell_count", "clock_cells"],
    )[0]
    if clock_cell_count is not None:
        clock_total_buffers = clock_cell_count
    elif clock_buffer_count is not None or clock_inverter_count is not None:
        clock_total_buffers = (clock_buffer_count or 0) + (clock_inverter_count or 0)
    else:
        clock_total_buffers = None

    return ClockMetrics(
        clock_skew_ps=clock_skew_ps,
        clock_latency_ns=q(
            "Clock",
            "Clock Insertion Latency",
            ["CTS", "STA", "Route"],
            [
                "cts_worst_max_insertion_latency_ns",
                "worst_max_insertion_latency_ns",
                "cts_insertion_latency_ns",
                "worst_insertion_latency_ns",
                "clock_latency",
                "latency_ns",
                "insertion_latency",
                "clock_insertion_delay",
                "cts_latency",
                "insertion_delay",
            ],
        )[0],
        clock_wirelength_um=q(
            "Clock",
            "Clock Wirelength",
            ["CTS", "Route"],
            [
                "total_clock_wirelength",
                "CTS.total_clock_wirelength",
                "clock_wirelength",
                "clock_wire_length",
                "clock_wirelength_um",
            ],
        )[0],
        clock_max_wirelength_um=q(
            "Clock",
            "Max Clock Wirelength",
            ["CTS", "Route"],
            ["cts_clock_wirelength_max", "max_clock_wirelength", "CTS.max_clock_wirelength"],
        )[0],
        clock_buffer_count=clock_buffer_count,
        clock_inverter_count=clock_inverter_count,
        clock_total_buffers=clock_total_buffers,
        clock_buffer_area_um2=q(
            "Clock",
            "Clock Buffer Area",
            ["CTS", "Route"],
            ["cts_buffer_area", "CTS.buffer_area", "buffer_area", "clock_buffer_area"],
        )[0],
        clock_path_max_buffer=q(
            "Clock",
            "Clock Path Max Buffer",
            ["CTS"],
            ["clock_path_max_buffer", "CTS.clock_path_max_buffer", "max_buffer_per_path"],
        )[0],
        clock_path_min_buffer=q(
            "Clock",
            "Clock Path Min Buffer",
            ["CTS"],
            ["clock_path_min_buffer", "CTS.clock_path_min_buffer", "min_buffer_per_path"],
        )[0],
        clock_nets_count=q(
            "Clock",
            "Clock Nets Count",
            ["CTS", "Route", "Harden"],
            ["Nets.num_clock", "num_clock_nets", "clock_nets", "num_clock"],
        )[0],
        clock_tree_levels=q(
            "Clock",
            "Clock Tree Levels",
            ["CTS", "STA"],
            [
                "cts_clock_tree_max_level",
                "CTS.max_level_of_clock_tree",
                "max_level_of_clock_tree",
                "clock_tree_max_level",
                "clock_tree_levels",
                "clock_levels",
                "tree_depth",
                "max_level",
                "clock_max_level",
            ],
        )[0],
        clock_cell_count=clock_cell_count,
    )
