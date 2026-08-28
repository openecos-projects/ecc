"""Per-family section extractors for the design-summary report.

Each extractor resolves one metrics family through the shared query helper
(`q`, a thin wrapper around :func:`StepMetricStore.query` plus the
parameters/home fallback), mirroring the GUI extractor's section order.
"""

from chipcompiler.engine.signoff.report_data import (
    CongestionMetrics,
    DesignReportWarning,
    ExecutionMetrics,
    PhysicalMetrics,
    PowerMetrics,
    RoutingMetrics,
    StageExecutionRecord,
    VerificationMetrics,
    canonicalize_stage_name,
)
from chipcompiler.engine.signoff.report_extract import (
    _is_record,
    _parse_number,
    format_duration,
    parse_runtime_seconds,
)

_AREA_STAGES = ["Harden", "Route", "Legal", "Place", "Floor"]


def _normalize_area(value):
    """GUI rule: a die/core area below 100 was reported in mm²."""
    if value is not None and value < 100:
        return value * 1e6
    return value


def _extract_physical(q, warnings) -> PhysicalMetrics:
    die_area_um2 = _normalize_area(
        q(
            "Physical",
            "Die Area",
            _AREA_STAGES,
            [
                "Design Layout.die_area",
                "die_area_um2",
                "die_area",
                "dieArea",
                "die_area_um",
                "die_area_mm2",
            ],
        )[0]
    )
    core_area_um2 = _normalize_area(
        q(
            "Physical",
            "Core Area",
            _AREA_STAGES,
            ["Design Layout.core_area", "core_area_um2", "core_area", "coreArea", "core_area_um"],
        )[0]
    )
    core_utilization_pct = q(
        "Physical",
        "Core Utilization",
        _AREA_STAGES,
        [
            "Design Layout.core_usage",
            "Design Layout.die_usage",
            "core_utilization",
            "utilization",
            "core_utilization_pct",
            "utilization_pct",
            "coreUtilization",
        ],
    )[0]
    if core_utilization_pct is not None and 0 < core_utilization_pct <= 1.0:
        core_utilization_pct = round(core_utilization_pct * 100, 2)
    if core_utilization_pct is not None and not (0 <= core_utilization_pct <= 100):
        warnings.append(
            DesignReportWarning(
                "PHYS_UTIL_OUT_OF_RANGE",
                f"Core utilization {core_utilization_pct}% is outside standard range (0-100%).",
            )
        )
    return PhysicalMetrics(
        die_area_um2=die_area_um2,
        die_area_mm2=round(die_area_um2 / 1e6, 4) if die_area_um2 is not None else None,
        core_area_um2=core_area_um2,
        core_area_mm2=round(core_area_um2 / 1e6, 4) if core_area_um2 is not None else None,
        core_utilization_pct=core_utilization_pct,
        std_cell_area_um2=q(
            "Physical",
            "Standard Cell Area",
            _AREA_STAGES + ["Synth"],
            [
                "Instances.total.area",
                "Instances.logic.area",
                "design.area",
                "stdcell_area",
                "std_cell_area",
                "cell_area",
                "stdCellArea",
                "area",
            ],
        )[0],
        macro_area_um2=q(
            "Physical",
            "Macro Area",
            ["Harden", "Route", "Place", "Floor"],
            ["Instances.macros.area", "macro_area", "macro_area_um2", "macroArea"],
        )[0],
        macro_count=q(
            "Physical",
            "Macro Count",
            ["Harden", "Route", "Place", "Floor"],
            ["Instances.macros.num", "macro_count", "num_macros", "macroCount"],
        )[0],
        instance_count=q(
            "Physical",
            "Total Instances",
            ["Harden", "Route", "Legal", "Place", "CTS", "Fanout", "Floor", "Synth"],
            [
                "Design Statis.num_instances",
                "Instances.total.num",
                "design.num_cells",
                "instance_count",
                "instances",
                "instanceCount",
                "num_cells",
                "total_instances",
            ],
        )[0],
        sequential_cell_count=q(
            "Physical",
            "Sequential Cell Count",
            ["Harden", "Route", "CTS", "Place", "Synth"],
            [
                "Instances.clock.num",
                "sequential_cells",
                "seq_cells",
                "sequential_cell_count",
                "flip_flops",
                "registers",
            ],
        )[0],
        combinational_cell_count=q(
            "Physical",
            "Combinational Cell Count",
            ["Harden", "Route", "Place", "Synth"],
            [
                "Instances.logic.num",
                "combinational_cells",
                "comb_cells",
                "combinational_cell_count",
                "logic_cells",
            ],
        )[0],
        io_pin_count=q(
            "Physical",
            "IO Pin Count",
            ["Harden", "Route", "Floor", "Synth"],
            [
                "Design Statis.num_iopins",
                "Instances.total.pin_num",
                "design.num_ports",
                "io_pin_count",
                "io_pins",
                "ioPins",
                "num_ports",
                "pins",
            ],
        )[0],
        net_count=q(
            "Physical",
            "Total Nets",
            ["Harden", "Route", "Legal", "Place", "CTS", "Fanout", "Floor", "Synth"],
            [
                "Design Statis.num_nets",
                "design.num_wires",
                "net_count",
                "nets",
                "netCount",
                "num_wires",
            ],
        )[0],
    )


def _extract_routing(q) -> RoutingMetrics:
    routing_completion_pct = q(
        "Routing",
        "Routing Completion",
        ["Route", "Harden", "STA"],
        [
            "routing_completion",
            "routing_completion_pct",
            "route_completion",
            "route_completion_pct",
            "completion_pct",
            "drc_completion",
            "routed_pct",
            "Nets.routed_pct",
            "routed_nets_pct",
            "route_dr_routed_net_pct",
        ],
    )[0]
    if routing_completion_pct is not None and 0 < routing_completion_pct <= 1.0:
        routing_completion_pct = round(routing_completion_pct * 100, 1)
    return RoutingMetrics(
        hpwl_um=q(
            "Routing",
            "Half-Perimeter Wirelength",
            ["Place", "Floor"],
            ["place_hpwl", "hpwl", "hpwl_um", "half_perimeter_wirelength"],
        )[0],
        estimated_wirelength_um=q(
            "Routing",
            "Estimated Wirelength",
            ["Place", "CTS", "Route"],
            [
                "place_flute_wirelength",
                "place_grwl",
                "estimated_wirelength",
                "estimated_wirelength_um",
            ],
        )[0],
        routed_wirelength_um=q(
            "Routing",
            "Routed Wirelength",
            ["Route", "Harden"],
            [
                "route_dr_total_wirelength",
                "route_wirelength",
                "Nets.wire_len",
                "routed_wirelength",
                "routed_wirelength_um",
                "wirelength",
                "wire_len",
            ],
        )[0],
        via_count=q(
            "Routing",
            "Via Count",
            ["Route", "Harden"],
            [
                "route_dr_total_via_count",
                "route_via_count",
                "Nets.num_via",
                "via_count",
                "vias",
                "num_vias",
                "num_via",
            ],
        )[0],
        routing_completion_pct=routing_completion_pct,
        route_drc_count=q(
            "Routing",
            "Route DRC Violations",
            ["Route"],
            [
                "route_dr_total_violation_count",
                "route_drc_count",
                "drc_violations",
                "route_violations",
            ],
        )[0],
    )


def _extract_congestion(q) -> CongestionMetrics:
    return CongestionMetrics(
        global_overflow_total=q(
            "Congestion",
            "Global Overflow Total",
            ["Route", "Place"],
            [
                "route_la_total_overflow",
                "place_congestion_egr_overflow_total",
                "global_overflow",
                "global_overflow_total",
                "total_overflow",
            ],
        )[0],
        global_overflow_pct=q(
            "Congestion",
            "Global Overflow Pct",
            ["Route", "Place"],
            ["global_overflow_pct", "overflow_pct"],
        )[0],
        max_overflow=q(
            "Congestion",
            "Max Overflow",
            ["Route", "Place"],
            ["place_congestion_egr_overflow_max", "max_overflow", "peak_overflow"],
        )[0],
        horizontal_congestion_pct=q(
            "Congestion",
            "Horizontal Congestion Pct",
            ["Place", "Route"],
            [
                "place_rudy_utilization_max",
                "place_lutrudy_utilization_max",
                "horizontal_congestion_pct",
                "h_congestion_pct",
            ],
        )[0],
        vertical_congestion_pct=q(
            "Congestion",
            "Vertical Congestion Pct",
            ["Place", "Route"],
            ["place_rudy_utilization_max", "vertical_congestion_pct", "v_congestion_pct"],
        )[0],
        hotspots_count=q(
            "Congestion",
            "Congestion Hotspots",
            ["Route", "Place"],
            ["hotspots_count", "num_hotspots", "hotspot_count"],
        )[0],
    )


def _extract_power(q, params) -> PowerMetrics:
    dynamic_power_mw = q(
        "Power",
        "Dynamic Power",
        ["Power", "STA", "Route", "Harden"],
        [
            "dynamic_power",
            "dynamic_power_mw",
            "power.dynamic",
            "power_dynamic",
            "sta_dynamic_power",
        ],
    )[0]
    leakage_power_mw = q(
        "Power",
        "Leakage Power",
        ["Power", "STA", "Route", "Harden"],
        [
            "leakage_power",
            "leakage_power_mw",
            "power.leakage",
            "power_leakage",
            "sta_leakage_power",
        ],
    )[0]
    total_power_mw = q(
        "Power",
        "Total Power",
        ["Power", "STA", "Route", "Harden"],
        [
            "total_power",
            "total_power_mw",
            "power.total",
            "power_total",
            "power_mw",
            "sta_total_power",
            "power.total_power",
        ],
    )[0]
    if total_power_mw is None and (dynamic_power_mw is not None or leakage_power_mw is not None):
        total_power_mw = round((dynamic_power_mw or 0) + (leakage_power_mw or 0), 3)
    return PowerMetrics(
        total_power_mw=total_power_mw,
        dynamic_power_mw=dynamic_power_mw,
        switching_power_mw=q(
            "Power",
            "Switching Power",
            ["Power", "STA", "Route", "Harden"],
            ["switching_power", "switching_power_mw", "power.switching", "power_switching"],
        )[0],
        internal_power_mw=q(
            "Power",
            "Internal Power",
            ["Power", "STA", "Route", "Harden"],
            ["internal_power", "internal_power_mw", "power.internal", "power_internal"],
        )[0],
        leakage_power_mw=leakage_power_mw,
        voltage_v=q(
            "Power",
            "Operating Voltage",
            ["Power", "STA", "Parameters"],
            ["voltage", "voltage_v", "VOLTAGE", "VDD", "vdd", "supply_voltage"],
        )[0],
        temperature_c=q(
            "Power",
            "Operating Temperature",
            ["Power", "STA", "Parameters"],
            ["temperature", "temperature_c", "TEMPERATURE", "TEMP", "temp", "operating_temp"],
        )[0],
        corner=params.get("POWER_CORNER") if isinstance(params.get("POWER_CORNER"), str) else None,
        activity_method=(
            params.get("POWER_ACTIVITY") if isinstance(params.get("POWER_ACTIVITY"), str) else None
        ),
    )


def _extract_verification(q) -> VerificationMetrics:
    drc_count = q(
        "Verification",
        "DRC Violations",
        ["DRC", "Harden", "Route"],
        ["drc_count", "drc_violations", "violations_count", "errors", "drc_errors"],
    )[0]
    drc_status = "unrun" if drc_count is None else ("clean" if drc_count == 0 else "violations")
    lvs_mismatch_count = q(
        "Verification",
        "LVS Mismatches",
        ["LVS", "Harden"],
        ["lvs_count", "lvs_mismatches", "mismatches", "lvs_errors"],
    )[0]
    lvs_status = (
        "unrun"
        if lvs_mismatch_count is None
        else ("matched" if lvs_mismatch_count == 0 else "mismatch")
    )
    return VerificationMetrics(
        drc_count=drc_count,
        drc_status=drc_status,
        lvs_status=lvs_status,
        lvs_mismatch_count=lvs_mismatch_count,
        antenna_violations=q(
            "Verification",
            "Antenna Violations",
            ["DRC", "Route"],
            ["antenna_violations", "antenna_errors", "antenna_count"],
        )[0],
        erc_violations=q(
            "Verification",
            "ERC Violations",
            ["DRC", "LVS"],
            ["erc_violations", "erc_errors", "erc_count"],
        )[0],
        floating_nets_count=q(
            "Verification",
            "Floating Nets",
            ["LVS", "DRC"],
            ["floating_nets", "floating_net_count"],
        )[0],
        unconnected_pins_count=q(
            "Verification",
            "Unconnected Pins",
            ["LVS", "DRC"],
            ["unconnected_pins", "unconnected_pin_count"],
        )[0],
    )


def _extract_execution(flow) -> ExecutionMetrics:
    stages = []
    total_runtime_seconds = 0.0
    peak_memory_mb = None
    steps = flow.get("steps") if isinstance(flow.get("steps"), list) else []
    for raw_step in steps:
        if not _is_record(raw_step):
            continue
        name = raw_step.get("name") if isinstance(raw_step.get("name"), str) else "Unknown"
        tool = raw_step.get("tool") if isinstance(raw_step.get("tool"), str) else name
        state = raw_step.get("state") if isinstance(raw_step.get("state"), str) else "Unknown"
        runtime_seconds = parse_runtime_seconds(raw_step.get("runtime"))
        info = raw_step.get("info") if _is_record(raw_step.get("info")) else {}
        memory_mb = _parse_number(
            raw_step.get(
                "peak memory (mb)",
                raw_step.get(
                    "peak_memory_mb", raw_step.get("peakMemoryMb", info.get("peak memory (mb)"))
                ),
            )
        )
        if runtime_seconds is not None:
            total_runtime_seconds += runtime_seconds
        if memory_mb is not None and (peak_memory_mb is None or memory_mb > peak_memory_mb):
            peak_memory_mb = memory_mb
        stages.append(
            StageExecutionRecord(
                stage=canonicalize_stage_name(name),
                tool=tool,
                runtime_seconds=runtime_seconds,
                runtime_formatted=format_duration(runtime_seconds),
                peak_memory_mb=memory_mb,
                state=state,
            )
        )
    return ExecutionMetrics(
        total_runtime_seconds=total_runtime_seconds if total_runtime_seconds > 0 else None,
        total_runtime_formatted=format_duration(total_runtime_seconds),
        peak_memory_mb=peak_memory_mb,
        stages=stages,
    )
