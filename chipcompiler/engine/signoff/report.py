"""Design-summary report extraction for an ECC workspace.

Python port of the ECOS Studio GUI extractor
(ecos/gui/packages/shared/src/utils/designReportExtract.ts), essence rather
than line-by-line: the data contract, the alias-based multi-stage metric
lookup, the derived-value rules, and the workspace file walk. Deliberately
trimmed relative to the GUI: no resource-index API branches, no hardcoded
corner candidates (STA corners come from the configured signoff matrix via
tools.ecc.sta_qor), no LaTeX/Markdown/CSV/Typst formatting concerns, and no
DRC statis-CSV parsing (the DRC stage metrics already carry the counts).
"""

from datetime import UTC, datetime

# Data contract, parsers, and lookup helpers live in sibling modules to keep
# each under the repo's file-size bar; re-exported here as the public surface.
from chipcompiler.engine.signoff.report_data import (  # noqa: F401
    ClockMetrics,
    CongestionMetrics,
    CornerTimingRecord,
    DesignInfo,
    DesignReportData,
    DesignReportWarning,
    EvidenceProvenanceRecord,
    ExecutionMetrics,
    PhysicalMetrics,
    PowerMetrics,
    RoutingMetrics,
    StageExecutionRecord,
    TimingMetrics,
    VerificationMetrics,
    canonicalize_stage_name,
)
from chipcompiler.engine.signoff.report_extract import (  # noqa: F401
    STEP_DIRS,
    StepMetricStore,
    _find_metric_in_record,
    _first_str,
    _get_nested_value,
    _is_record,
    _parse_corner_attributes,
    _parse_number,
    _query,
    collect_workspace_report,
    format_duration,
    parse_power_rpt,
    parse_qor_summary_rpt,
    parse_runtime_seconds,
)
from chipcompiler.engine.signoff.report_sections import (  # noqa: F401
    _AREA_STAGES,
    _extract_congestion,
    _extract_execution,
    _extract_physical,
    _extract_power,
    _extract_routing,
    _extract_verification,
)
from chipcompiler.engine.signoff.report_timing import (  # noqa: F401
    _extract_clock,
    _extract_corner_records,
    _extract_timing,
)


def extract_design_report_data(inputs) -> DesignReportData:
    """Build a DesignReportData from collected workspace inputs.

    `inputs` carries: design_name, top_module, pdk, pdk_version,
    frequency_target, parameters, flow, home_data, step_metrics,
    step_summaries, step_hotspots, sta_timing_issues, sta_corner_reports,
    version_info (dict), generated_at, workspace_name, workspace_path.
    """
    warnings: list[DesignReportWarning] = []
    provenance: list[EvidenceProvenanceRecord] = []

    params = inputs.get("parameters") or {}
    flow = inputs.get("flow") or {}
    home = inputs.get("home_data") or {}
    version_info = inputs.get("version_info") or {}

    design, run_id, timestamp = _extract_design_info(inputs, params, flow, home, version_info)

    store = StepMetricStore()
    store.run_id = run_id
    store.timestamp = timestamp
    for source in ("step_metrics", "step_summaries", "step_hotspots"):
        for stage, payload in (inputs.get(source) or {}).items():
            store.add(stage, payload)
    if _is_record(inputs.get("sta_timing_issues")):
        store.add("STA", inputs["sta_timing_issues"])
    if params:
        store.add("Parameters", params)
    if home:
        store.add("Home", home)
        store.add("Parameters", home)

    def q(category, display_name, stage_priority, aliases, unit=""):
        return _query(
            store, params, home, provenance, category, display_name, stage_priority, aliases, unit
        )

    physical = _extract_physical(q, warnings)
    corners = _extract_corner_records(store, inputs)
    timing = _extract_timing(q, inputs, corners)
    clock = _extract_clock(q)
    routing = _extract_routing(q)
    congestion = _extract_congestion(q)
    power = _extract_power(q, params)
    verification = _extract_verification(q)
    execution = _extract_execution(flow)

    return DesignReportData(
        design=design,
        physical=physical,
        timing=timing,
        multi_corner_timing=corners,
        clock=clock,
        routing=routing,
        congestion=congestion,
        power=power,
        verification=verification,
        execution=execution,
        provenance=provenance,
        warnings=warnings,
    )


def _extract_design_info(inputs, params, flow, home, version_info):
    """Resolve DesignInfo plus the run_id/timestamp the store needs."""
    design_name = (
        _first_str(
            inputs.get("design_name"),
            inputs.get("top_module"),
            params.get("Design"),
            params.get("DESIGN"),
            params.get("DESIGN_NAME"),
            params.get("top_module"),
            params.get("TOP_MODULE"),
            flow.get("design") if _is_record(flow) else None,
            home.get("design") if _is_record(home) else None,
            inputs.get("workspace_name"),
        )
        or "Unknown_Design"
    )
    pdk = (
        _first_str(
            inputs.get("pdk"),
            params.get("PDK"),
            params.get("pdk"),
            flow.get("pdk") if _is_record(flow) else None,
            home.get("pdk") if _is_record(home) else None,
        )
        or "sky130hd"
    )
    pdk_version = _first_str(
        params.get("PDK_VERSION"),
        params.get("pdk_version"),
        home.get("pdk_version") if _is_record(home) else None,
    )
    pdk_commit = _first_str(
        params.get("PDK_COMMIT"),
        params.get("pdk_commit"),
        params.get("PDK_GIT_COMMIT"),
        params.get("pdk_git_commit"),
        params.get("PDK_COMMIT_ID"),
        params.get("pdk_commit_id"),
        params.get("pdkCommit"),
        home.get("pdk_commit") if _is_record(home) else None,
        home.get("pdk_commit_id") if _is_record(home) else None,
        home.get("pdkCommit") if _is_record(home) else None,
        home.get("pdk_git_commit") if _is_record(home) else None,
        home.get("commit") if _is_record(home) else None,
        home.get("commit_id") if _is_record(home) else None,
        home.get("git_commit") if _is_record(home) else None,
    )
    ecc_tool = (
        _first_str(
            version_info.get("ecc_tools"),
            params.get("ECC_TOOL"),
            params.get("ecc_tool"),
            flow.get("tool") if _is_record(flow) else None,
        )
        or "ecc"
    )
    if ecc_tool == "unknown":
        ecc_tool = "ecc"
    raw_ecc_version = _first_str(
        version_info.get("ecc"),
        params.get("ECC_VERSION"),
        params.get("ecc_version"),
        home.get("ecc_version") if _is_record(home) else None,
    )
    ecc_version = None if raw_ecc_version == "unknown" else raw_ecc_version
    ecos_studio_version = _first_str(
        version_info.get("gui"),
        params.get("ECOS_STUDIO_VERSION"),
        params.get("ecos_studio_version"),
    )
    run_id = _first_str(
        params.get("RUN_ID"),
        params.get("run_id"),
        flow.get("run_id") if _is_record(flow) else None,
    )
    timestamp = (
        _first_str(
            flow.get("timestamp") if _is_record(flow) else None,
            params.get("timestamp"),
        )
        or datetime.now(UTC).isoformat()
    )
    flow_tools = flow.get("tools") if _is_record(flow.get("tools")) else {}
    tool_versions = {k: v for k, v in flow_tools.items() if isinstance(v, str)}
    design = DesignInfo(
        design_name=design_name,
        workspace_name=inputs.get("workspace_name") or design_name,
        workspace_path=inputs.get("workspace_path") or "",
        pdk=pdk,
        pdk_version=pdk_version,
        pdk_commit=pdk_commit,
        ecc_tool=ecc_tool,
        ecc_version=ecc_version,
        ecos_studio_version=ecos_studio_version,
        tool_versions=tool_versions,
        git_commit=_first_str(params.get("GIT_COMMIT"), params.get("git_commit")),
        run_id=run_id,
        timestamp=timestamp,
        generated_at=inputs.get("generated_at") or timestamp,
    )
    return design, run_id, timestamp


def generate_text_report(workspace, *, refresh_analysis: bool = False) -> str:
    """Render the text design summary for a workspace.

    Default is extract-as-is: the engine refreshes each step's analysis
    after it succeeds, and inspect/export already refresh on their path.
    """
    if refresh_analysis:
        from chipcompiler.engine import EngineFlow, SignoffPackageOptions

        EngineFlow(workspace).collect_signoff_package(
            SignoffPackageOptions(archive=False, materialize=False, refresh_analysis=True)
        )
    from chipcompiler.engine.signoff.report_text import format_text_report

    return format_text_report(collect_workspace_report(workspace))
