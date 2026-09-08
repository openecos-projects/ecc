"""Data contract for the design-summary report.

Mirrors ecos/gui/packages/shared/src/contracts/designReport.ts (snake_case)
plus the stage-name canonicalization table shared by extraction and
formatting.
"""

import dataclasses

STAGE_CANONICAL_NAMES = {
    "synthesis": "Synth",
    "synth": "Synth",
    "synthesis_yosys": "Synth",
    "yosys": "Synth",
    "floorplan": "Floor",
    "floor": "Floor",
    "floorplan_ecc": "Floor",
    "macro_placement": "Floor",
    "lec": "LEC",
    "postroutelec": "LEC",
    "postroutelec_yosys_lec": "LEC",
    "placement": "Place",
    "place": "Place",
    "place_dreamplace": "Place",
    "dreamplace": "Place",
    "global_placement": "Place",
    "detailed_placement": "Place",
    "cts": "CTS",
    "cts_ecc": "CTS",
    "legalization": "Legal",
    "legal": "Legal",
    "legalization_dreamplace": "Legal",
    "routing": "Route",
    "route": "Route",
    "route_ecc": "Route",
    "global_route": "Route",
    "detail_route": "Route",
    "drc": "DRC",
    "drc_ecc": "DRC",
    "lvs": "LVS",
    "lvs_ecc": "LVS",
    "filler": "Filler",
    "filler_ecc": "Filler",
    "rcx": "RCX",
    "rcx_ecc": "RCX",
    "sta": "STA",
    "sta_ecc": "STA",
    "sta_signoff": "STA",
    "signoff": "STA",
    "post_route_sta": "STA",
    "sta_corner": "STA",
    "power": "Power",
    "power_ecc": "Power",
    "sta_power": "Power",
    "harden": "Harden",
    "harden_ecc": "Harden",
}


# ---------------------------------------------------------------------------
# Data contract (mirrors ecos/gui/packages/shared/src/contracts/designReport.ts)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class DesignInfo:
    design_name: str = "Unknown_Design"
    workspace_name: str = ""
    workspace_path: str = ""
    pdk: str = ""
    pdk_version: str | None = None
    pdk_commit: str | None = None
    ecc_tool: str | None = None
    ecc_version: str | None = None
    ecos_studio_version: str | None = None
    tool_versions: dict = dataclasses.field(default_factory=dict)
    git_commit: str | None = None
    run_id: str | None = None
    timestamp: str = ""
    generated_at: str = ""


@dataclasses.dataclass
class PhysicalMetrics:
    die_area_um2: float | None = None
    die_area_mm2: float | None = None
    core_area_um2: float | None = None
    core_area_mm2: float | None = None
    core_utilization_pct: float | None = None
    std_cell_area_um2: float | None = None
    macro_area_um2: float | None = None
    macro_count: float | None = None
    instance_count: float | None = None
    sequential_cell_count: float | None = None
    combinational_cell_count: float | None = None
    io_pin_count: float | None = None
    net_count: float | None = None


@dataclasses.dataclass
class TimingMetrics:
    target_clock_period_ns: float | None = None
    target_frequency_mhz: float | None = None
    fmax_mhz: float | None = None
    setup_wns_ns: float | None = None
    setup_tns_ns: float | None = None
    hold_wns_ns: float | None = None
    hold_tns_ns: float | None = None
    violating_endpoints_setup: float | None = None
    violating_endpoints_hold: float | None = None
    slew_violations: float | None = None
    cap_violations: float | None = None
    fanout_violations: float | None = None
    critical_path_delay_ns: float | None = None


@dataclasses.dataclass
class CornerTimingRecord:
    corner: str
    process_corner: str | None = None
    voltage_v: float | None = None
    temperature_c: float | None = None
    rc_corner: str | None = None
    setup_wns_ns: float | None = None
    setup_tns_ns: float | None = None
    hold_wns_ns: float | None = None
    hold_tns_ns: float | None = None
    violating_endpoints_setup: float | None = None
    violating_endpoints_hold: float | None = None
    status: str = "unknown"


@dataclasses.dataclass
class ClockMetrics:
    clock_skew_ps: float | None = None
    clock_latency_ns: float | None = None
    clock_wirelength_um: float | None = None
    clock_max_wirelength_um: float | None = None
    clock_buffer_count: float | None = None
    clock_inverter_count: float | None = None
    clock_total_buffers: float | None = None
    clock_buffer_area_um2: float | None = None
    clock_path_max_buffer: float | None = None
    clock_path_min_buffer: float | None = None
    clock_nets_count: float | None = None
    clock_tree_levels: float | None = None
    clock_cell_count: float | None = None


@dataclasses.dataclass
class RoutingMetrics:
    hpwl_um: float | None = None
    estimated_wirelength_um: float | None = None
    routed_wirelength_um: float | None = None
    via_count: float | None = None
    routing_completion_pct: float | None = None
    route_drc_count: float | None = None


@dataclasses.dataclass
class CongestionMetrics:
    global_overflow_total: float | None = None
    global_overflow_pct: float | None = None
    max_overflow: float | None = None
    horizontal_congestion_pct: float | None = None
    vertical_congestion_pct: float | None = None
    hotspots_count: float | None = None


@dataclasses.dataclass
class PowerMetrics:
    total_power_mw: float | None = None
    dynamic_power_mw: float | None = None
    switching_power_mw: float | None = None
    internal_power_mw: float | None = None
    leakage_power_mw: float | None = None
    voltage_v: float | None = None
    temperature_c: float | None = None
    corner: str | None = None
    activity_method: str | None = None


@dataclasses.dataclass
class VerificationMetrics:
    drc_count: float | None = None
    drc_status: str = "unrun"
    lvs_status: str = "unrun"
    lvs_mismatch_count: float | None = None
    antenna_violations: float | None = None
    erc_violations: float | None = None
    floating_nets_count: float | None = None
    unconnected_pins_count: float | None = None


@dataclasses.dataclass
class StageExecutionRecord:
    stage: str
    tool: str
    runtime_seconds: float | None = None
    runtime_formatted: str | None = None
    peak_memory_mb: float | None = None
    state: str = "Unknown"


@dataclasses.dataclass
class ExecutionMetrics:
    total_runtime_seconds: float | None = None
    total_runtime_formatted: str | None = None
    peak_memory_mb: float | None = None
    stages: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class EvidenceProvenanceRecord:
    category: str
    metric: str
    value: float
    unit: str
    status: str
    stage: str
    corner: str | None
    tool: str
    source_metric_id: str
    run_id: str
    timestamp: str


@dataclasses.dataclass
class DesignReportWarning:
    code: str
    message: str
    severity: str = "warn"


@dataclasses.dataclass
class DesignReportData:
    design: DesignInfo = dataclasses.field(default_factory=DesignInfo)
    physical: PhysicalMetrics = dataclasses.field(default_factory=PhysicalMetrics)
    timing: TimingMetrics = dataclasses.field(default_factory=TimingMetrics)
    multi_corner_timing: list = dataclasses.field(default_factory=list)
    clock: ClockMetrics = dataclasses.field(default_factory=ClockMetrics)
    routing: RoutingMetrics = dataclasses.field(default_factory=RoutingMetrics)
    congestion: CongestionMetrics = dataclasses.field(default_factory=CongestionMetrics)
    power: PowerMetrics = dataclasses.field(default_factory=PowerMetrics)
    verification: VerificationMetrics = dataclasses.field(default_factory=VerificationMetrics)
    execution: ExecutionMetrics = dataclasses.field(default_factory=ExecutionMetrics)
    provenance: list = dataclasses.field(default_factory=list)
    warnings: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class ParsedPowerMetrics:
    total_power_mw: float | None = None
    dynamic_power_mw: float | None = None
    leakage_power_mw: float | None = None
    internal_power_mw: float | None = None
    switching_power_mw: float | None = None
    voltage_v: float | None = None


@dataclasses.dataclass
class ParsedQorSummaryMetrics:
    wns: float | None = None
    tns: float | None = None
    nvp: float | None = None
    frequency_mhz: float | None = None
    hold_wns: float | None = None
    hold_tns: float | None = None
    hold_nvp: float | None = None


def canonicalize_stage_name(name: str) -> str:
    return STAGE_CANONICAL_NAMES.get(name.lower(), name)
