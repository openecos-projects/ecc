"""Text design-summary formatter.

Mechanical port of the ECOS Studio GUI text formatter
(ecos/gui/packages/shared/src/utils/designReportFormatters/textFormatter.ts)
so CLI and GUI render byte-identical reports from the same
:class:`~chipcompiler.engine.signoff.report.DesignReportData`.
"""

from chipcompiler.engine.signoff.report import DesignReportData

WIDTH = 78
_PLACEHOLDER = "—"


def _pad_right(text: str, width: int) -> str:
    return text if len(text) >= width else text + " " * (width - len(text))


def _pad_left(text: str, width: int) -> str:
    return text if len(text) >= width else " " * (width - len(text)) + text


def _fmt(val, unit: str = "", decimals: int = 2) -> str:
    if val is None:
        return _PLACEHOLDER
    if isinstance(val, bool):
        formatted = str(val)
    elif isinstance(val, int):
        formatted = f"{val:,}"
    elif isinstance(val, float):
        if val != val or val in (float("inf"), float("-inf")):
            return _PLACEHOLDER
        formatted = f"{int(val):,}" if val.is_integer() else f"{val:.{decimals}f}"
    else:
        formatted = str(val)
    return f"{formatted} {unit}" if unit else formatted


def _separator(char: str = "-") -> str:
    return char * WIDTH


def _title_bar(text: str) -> str:
    padded = f"  {text}  "
    side = max(0, (WIDTH - len(padded)) // 2)
    return "=" * side + padded + "=" * (WIDTH - side - len(padded))


def _section_header(text: str) -> str:
    return f"[ {text} ]"


def _row(metric: str, value: str, notes: str = "") -> str:
    return f"{_pad_right(f'  {metric}', 38)} {_pad_right(value, 20)} {notes}"


def format_text_report(
    data: DesignReportData,
    *,
    include_multi_corner: bool = True,
    include_stage_breakdown: bool = True,
) -> str:
    lines: list[str] = []

    lines.append(_title_bar("ECOS STUDIO — DESIGN SUMMARY REPORT"))
    lines.append(f"Design Name        : {data.design.design_name}")
    pdk_commit_short = f"@{data.design.pdk_commit[:8]}" if data.design.pdk_commit else None
    pdk_suffix = (
        f" ({pdk_commit_short})"
        if pdk_commit_short
        else f" ({data.design.pdk_version})"
        if data.design.pdk_version
        else ""
    )
    lines.append(f"PDK / Node         : {data.design.pdk}{pdk_suffix}")
    if data.design.ecos_studio_version:
        lines.append(f"ECOS Studio Version: {data.design.ecos_studio_version}")
    if data.design.git_commit:
        lines.append(f"Git Commit         : {data.design.git_commit}")
    lines.append(f"Generated          : {data.design.generated_at}")
    lines.append(_separator("="))
    lines.append("")

    physical = data.physical
    lines.append(_section_header("1. PHYSICAL & AREA METRICS"))
    lines.append(_separator("-"))
    die_value = _fmt(physical.die_area_um2, "um²")
    if physical.die_area_mm2 is not None:
        die_value += f" ({_fmt(physical.die_area_mm2, 'mm²', 4)})"
    lines.append(_row("Die Area", die_value, "Physical boundary"))
    lines.append(_row("Core Area", _fmt(physical.core_area_um2, "um²"), "Placement boundary"))
    lines.append(
        _row("Core Utilization", _fmt(physical.core_utilization_pct, "%"), "Placed cell density")
    )
    lines.append(
        _row("Standard Cell Area", _fmt(physical.std_cell_area_um2, "um²"), "Total stdcell area")
    )
    if physical.macro_count is not None and physical.macro_count > 0:
        lines.append(
            _row(
                "Macro Count / Area",
                f"{_fmt(physical.macro_count)} macros / {_fmt(physical.macro_area_um2, 'um²')}",
                "Hard macros",
            )
        )
    lines.append(_row("Total Instances", _fmt(physical.instance_count), "Cells placed"))
    if physical.sequential_cell_count is not None or physical.combinational_cell_count is not None:
        lines.append(
            _row(
                "Sequential / Comb. Cells",
                f"{_fmt(physical.sequential_cell_count)}"
                f" / {_fmt(physical.combinational_cell_count)}",
                "Flops / Gates",
            )
        )
    if physical.io_pin_count is not None:
        lines.append(_row("IO Pins", _fmt(physical.io_pin_count), "Chip IOs"))
    if physical.net_count is not None:
        lines.append(_row("Total Nets", _fmt(physical.net_count), "Nets"))
    lines.append("")

    timing = data.timing
    lines.append(_section_header("2. TIMING CLOSURE & PERFORMANCE"))
    lines.append(_separator("-"))
    lines.append(
        _row(
            "Target Clock Period",
            _fmt(timing.target_clock_period_ns, "ns"),
            f"Target freq: {_fmt(timing.target_frequency_mhz, 'MHz')}",
        )
    )
    lines.append(_row("Achieved Fmax", _fmt(timing.fmax_mhz, "MHz"), "Max operating frequency"))
    lines.append(
        _row(
            "Setup Slack (WNS / TNS)",
            f"{_fmt(timing.setup_wns_ns, 'ns')} / {_fmt(timing.setup_tns_ns, 'ns')}",
            "TIMING MET"
            if timing.setup_wns_ns is not None and timing.setup_wns_ns >= 0
            else "VIOLATION",
        )
    )
    lines.append(
        _row(
            "Hold Slack (WNS / TNS)",
            f"{_fmt(timing.hold_wns_ns, 'ns')} / {_fmt(timing.hold_tns_ns, 'ns')}",
            "TIMING MET"
            if timing.hold_wns_ns is not None and timing.hold_wns_ns >= 0
            else "VIOLATION",
        )
    )
    if timing.critical_path_delay_ns is not None:
        lines.append(
            _row(
                "Critical Path Delay", _fmt(timing.critical_path_delay_ns, "ns"), "Data path delay"
            )
        )
    if timing.violating_endpoints_setup is not None or timing.violating_endpoints_hold is not None:
        lines.append(
            _row(
                "Violating Endpoints (Setup/Hold)",
                f"{_fmt(timing.violating_endpoints_setup)}"
                f" / {_fmt(timing.violating_endpoints_hold)}",
                "Failing paths",
            )
        )
    if (
        timing.slew_violations is not None
        or timing.cap_violations is not None
        or timing.fanout_violations is not None
    ):
        lines.append(
            _row(
                "DRC Violations (Slew/Cap/Fanout)",
                f"{_fmt(timing.slew_violations)} / {_fmt(timing.cap_violations)}"
                f" / {_fmt(timing.fanout_violations)}",
                "Electrical DRC",
            )
        )
    lines.append("")

    clock = data.clock
    lines.append(_section_header("3. CLOCK TREE & QUALITY"))
    lines.append(_separator("-"))
    lines.append(
        _row("Clock Tree Depth", f"{_fmt(clock.clock_tree_levels)} levels", "Max tree depth")
    )
    if clock.clock_buffer_count is not None or clock.clock_total_buffers is not None:
        buf_str = (
            f"{clock.clock_buffer_count}"
            if clock.clock_buffer_count is not None
            else f"{clock.clock_total_buffers}"
        )
        area_str = (
            f" ({_fmt(clock.clock_buffer_area_um2, 'um²')})"
            if clock.clock_buffer_area_um2 is not None
            else ""
        )
        lines.append(_row("Clock Buffers", f"{buf_str}{area_str}", "CTS buffers"))
    if clock.clock_path_min_buffer is not None or clock.clock_path_max_buffer is not None:
        lines.append(
            _row(
                "Clock Path Buffers (Min/Max)",
                f"{_fmt(clock.clock_path_min_buffer)} / {_fmt(clock.clock_path_max_buffer)}",
                "Buffers per path range",
            )
        )
    if clock.clock_wirelength_um is not None:
        max_suffix = (
            f" (Max: {_fmt(clock.clock_max_wirelength_um, 'um')})"
            if clock.clock_max_wirelength_um is not None
            else ""
        )
        lines.append(
            _row(
                "Clock Wirelength",
                f"{_fmt(clock.clock_wirelength_um, 'um')}{max_suffix}",
                "Total clock routing",
            )
        )
    if clock.clock_nets_count is not None:
        lines.append(_row("Clock Nets", f"{_fmt(clock.clock_nets_count)} nets", "Clock net count"))
    if clock.clock_skew_ps is not None:
        lines.append(_row("Clock Skew", _fmt(clock.clock_skew_ps, "ps"), "Max skew"))
    if clock.clock_latency_ns is not None:
        lines.append(
            _row("Clock Insertion Latency", _fmt(clock.clock_latency_ns, "ns"), "Insertion delay")
        )
    lines.append("")

    if include_multi_corner and data.multi_corner_timing:
        lines.append(_section_header("4. MULTI-CORNER TIMING"))
        lines.append(_separator("-"))
        lines.append(
            f"  {_pad_right('Corner', 24)} {_pad_left('Setup WNS', 11)}"
            f" {_pad_left('Setup TNS', 11)} {_pad_left('Hold WNS', 11)}"
            f" {_pad_left('Hold TNS', 11)}  Status"
        )
        lines.append("  " + "-" * (WIDTH - 4))
        for corner in data.multi_corner_timing:
            status = (
                "PASS"
                if corner.status == "pass"
                else "FAIL"
                if corner.status == "fail"
                else _PLACEHOLDER
            )
            lines.append(
                f"  {_pad_right(corner.corner, 24)}"
                f" {_pad_left(_fmt(corner.setup_wns_ns, 'ns'), 11)}"
                f" {_pad_left(_fmt(corner.setup_tns_ns, 'ns'), 11)}"
                f" {_pad_left(_fmt(corner.hold_wns_ns, 'ns'), 11)}"
                f" {_pad_left(_fmt(corner.hold_tns_ns, 'ns'), 11)}  {status}"
            )
        lines.append("")

    routing, congestion = data.routing, data.congestion
    lines.append(_section_header("5. ROUTING & CONGESTION"))
    lines.append(_separator("-"))
    lines.append(_row("HPWL", _fmt(routing.hpwl_um, "um"), "Estimated wirelength"))
    lines.append(
        _row(
            "Routed Wirelength", _fmt(routing.routed_wirelength_um, "um"), "Final routed wirelength"
        )
    )
    lines.append(_row("Via Count", _fmt(routing.via_count), "Vias"))
    if congestion.global_overflow_total is not None or congestion.global_overflow_pct is not None:
        overflow = _fmt(congestion.global_overflow_total)
        if congestion.global_overflow_pct is not None:
            overflow += f" ({_fmt(congestion.global_overflow_pct, '%')})"
        lines.append(_row("Global Route Overflow", overflow, "Tracks overflow"))
    lines.append("")

    power = data.power
    lines.append(_section_header("6. POWER ANALYSIS"))
    lines.append(_separator("-"))
    lines.append(_row("Total Power", _fmt(power.total_power_mw, "mW"), "Total dissipation"))
    lines.append(_row("Dynamic Power", _fmt(power.dynamic_power_mw, "mW"), "Switching + Internal"))
    lines.append(_row("Leakage Power", _fmt(power.leakage_power_mw, "mW"), "Static power"))
    lines.append("")

    verification = data.verification
    lines.append(_section_header("7. PHYSICAL VERIFICATION"))
    lines.append(_separator("-"))
    drc_value = {
        "clean": "CLEAN (0 violations)",
        "violations": f"VIOLATIONS ({_fmt(verification.drc_count)})",
    }.get(verification.drc_status, "UNRUN")
    lines.append(
        _row("DRC Status", drc_value, "PASS" if verification.drc_status == "clean" else "FAIL")
    )
    lvs_value = {
        "matched": "MATCHED (Clean)",
        "mismatch": f"MISMATCHES ({_fmt(verification.lvs_mismatch_count)})",
    }.get(verification.lvs_status, "UNRUN")
    lines.append(
        _row("LVS Status", lvs_value, "PASS" if verification.lvs_status == "matched" else "FAIL")
    )
    lines.append("")

    execution = data.execution
    lines.append(_section_header("8. FLOW EXECUTION COST"))
    lines.append(_separator("-"))
    lines.append(
        _row(
            "Total Runtime",
            execution.total_runtime_formatted or _fmt(execution.total_runtime_seconds, "s"),
            "Wall clock time",
        )
    )
    lines.append(
        _row("Peak Memory Usage", _fmt(execution.peak_memory_mb, "MB"), "Max resident memory")
    )
    if include_stage_breakdown and execution.stages:
        lines.append("")
        lines.append(
            f"  {_pad_right('Stage', 18)} {_pad_right('Tool', 16)} {_pad_left('Runtime', 12)}"
            f" {_pad_left('Peak Mem', 12)}  State"
        )
        lines.append("  " + "-" * (WIDTH - 4))
        for stage in execution.stages:
            runtime = stage.runtime_formatted or _fmt(stage.runtime_seconds, "s")
            lines.append(
                f"  {_pad_right(stage.stage, 18)} {_pad_right(stage.tool, 16)}"
                f" {_pad_left(runtime, 12)}"
                f" {_pad_left(_fmt(stage.peak_memory_mb, 'MB'), 12)}  {stage.state}"
            )

    lines.append("")
    lines.append(_separator("="))
    lines.append("END OF REPORT")

    return "\n".join(lines)
