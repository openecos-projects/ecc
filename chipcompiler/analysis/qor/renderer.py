"""ASCII CLI renderer for the QoR analysis report (spec §12.1 layout).

The renderer takes the assembled analysis plus the loader inputs (for
the raw engineering numbers in the breakdown notes); passing only the
analysis renders the same layout without detail notes.
"""

WIDTH = 78


def _fmt(value, digits=1):
    return "—" if value is None else f"{value:.{digits}f}"


def _fmt_signed(value, unit="ns"):
    if value is None:
        return "—"
    if value == 0:
        return f"0{unit}"
    return f"{value:+g}{unit}" if unit else f"{value:+g}"


def _pct(value):
    return None if value is None else value * 100.0


def render(analysis, inputs=None) -> str:
    feasibility = analysis.feasibility
    evidence = analysis.evidence
    summary = analysis.scalar_summary
    record = analysis.qor_record

    lines: list = []
    lines.append("=" * WIDTH)
    lines.append(f"  ECC QoR ANALYSIS REPORT - Design: {analysis.design or '<design>'}")
    lines.append(f"  Workspace: {analysis.workspace}")
    lines.append("=" * WIDTH)

    lines.append(f"  FEASIBILITY STATUS : {_feasibility_line(feasibility)}")

    evidence_detail = (
        f"Integrity: {_fmt(_pct(evidence.integrity))}%, "
        f"Coverage: {_fmt(_pct(evidence.coverage))}%, "
        f"Consistency: {_fmt(_pct(evidence.consistency))}%"
    )
    lines.append(f"  EVIDENCE STATE     : {evidence.state} [{evidence_detail}]")

    lines.append(
        f"  QoR COMPOSITE      : {_fmt(summary.score)} / 100 "
        f"(Status: {summary.status}, Profile: {summary.profile})"
    )
    for warning in analysis.config_warnings:
        lines.append(f"  CONFIG WARNING     : {warning}")
    lines.append("-" * WIDTH)

    lines.append("  [PHYSICAL QoR RECORD BREAKDOWN]")
    for label, key, note in (
        ("Timing Quality (Q_T)      ", "timing", _timing_note(analysis)),
        ("Interconnect Quality (Q_I)", "interconnect", _interconnect_note(analysis)),
        ("Area Efficiency (Q_A)     ", "area", _area_note(analysis, inputs)),
        ("Power Quality (Q_P)       ", "power", _power_note(analysis, inputs)),
        ("Robustness (Q_R)          ", "robustness", _robustness_note(analysis, inputs)),
    ):
        dimension = record[key]
        lines.append(
            f"    {label}: {_fmt(dimension.value)} / 100 [{dimension.state}] {note}".rstrip()
        )
    lines.append("-" * WIDTH)

    blockers = [d for d in analysis.diagnoses if d.state == "FAIL"]
    watches = [d for d in analysis.diagnoses if d.state != "FAIL"]

    lines.append("  [PRIMARY DIAGNOSES]")
    if not blockers:
        lines.append("    (No active feasibility blockers detected)")
    for diagnosis in blockers:
        lines.append(
            f"  [FAIL] {diagnosis.diagnosis_id} "
            f"(Severity: {diagnosis.severity:.2f}, Confidence: {diagnosis.diagnosis_confidence})"
        )
        lines.append(f"       {diagnosis.interpretation}")
        for metric in diagnosis.supporting_metrics:
            lines.append(f"       --> {metric.name}: {metric.value:g} {metric.unit}".rstrip())
    lines.append("")
    lines.append("  [WATCH & OPPORTUNITY DIAGNOSES]")
    if not watches:
        lines.append("    (None)")
    for diagnosis in watches:
        label = "OPPORTUNITY" if diagnosis.state == "OPPORTUNITY" else "WATCH"
        lines.append(
            f"  [{label}] {diagnosis.diagnosis_id} "
            f"(Severity: {diagnosis.severity:.2f}, Confidence: {diagnosis.diagnosis_confidence})"
        )
        lines.append(f"       {diagnosis.interpretation}")
    lines.append("-" * WIDTH)

    from chipcompiler.analysis.qor.interventions import prioritize

    lines.append("  [PRIORITIZED INTERVENTION HYPOTHESES]")
    ranked = prioritize(analysis.diagnoses)
    if not ranked:
        lines.append("    (None)")
    for index, intervention in enumerate(ranked, start=1):
        tier_label = intervention.tier.replace("TIER_", "Tier ")
        tier_label = tier_label.replace("_FEASIBILITY", " (Feasibility)")
        tier_label = tier_label.replace("_BOTTLENECK", " (Quality Limiter)")
        tier_label = tier_label.replace("_OPPORTUNITY", " (Opportunity)")
        lines.append(f"    {index}. [{tier_label}] {intervention.hypothesis}")
    lines.append("=" * WIDTH)
    return "\n".join(lines)


def _feasibility_line(feasibility) -> str:
    if feasibility.status == "PASS":
        return "PASS [All 7 Physical Signoff Gates Clean]"
    failed = [gate.id for gate in feasibility.gates if gate.state == "failed"]
    if failed:
        return f"PHYSICAL_FAIL [Failed gates: {', '.join(failed)}]"
    unverified = [
        f"{gate.id}({gate.availability})"
        for gate in feasibility.gates
        if gate.state == "unavailable"
    ]
    return f"{feasibility.status} [Gates awaiting evidence: {', '.join(unverified) or 'none'}]"


def _timing_note(analysis):
    slack = None
    for gate in analysis.feasibility.gates:
        if gate.id == "GATE_SETUP_SLACK" and gate.timing_slack is not None:
            slack = gate.timing_slack
    if slack is None:
        return "(WS: —)"
    return f"(WS: {_fmt_signed(slack.ws_ns)}, WNS: {_fmt_signed(slack.wns_ns)})"


def _interconnect_note(analysis):
    inflation = analysis.inflation
    if inflation.i_total is not None:
        i_text = f"I_total: {_fmt(inflation.i_total, 3)}"
    elif inflation.i_place is not None:
        i_text = (
            f"I_place: {_fmt(inflation.i_place, 3)} ({inflation.compatibility_status} route side)"
        )
    else:
        return "(I: —)"
    congestion = (
        f"S_cong: {_fmt(inflation.congestion_severity, 2)}"
        if inflation.congestion_severity is not None
        else "S_cong: —"
    )
    return f"({i_text}, {congestion})"


def _area_note(analysis, inputs):
    if inputs is None:
        return ""
    utilization = inputs.value("core_utilization")
    if utilization is None:
        return ""
    return f"(Core Util: {utilization * 100:.1f}%)"


def _power_note(analysis, inputs):
    if analysis.qor_record["power"].value is not None and inputs is not None:
        total = inputs.power_total_uw
        if total is not None:
            return f"(Ptotal: {_fmt(total / 1e6, 3)}W of {_fmt(inputs.power_budget_uw / 1e6, 3)}W)"
        return ""
    if inputs is not None and inputs.power_budget_uw is None:
        return "(No budget declared)"
    return "(UNKNOWN)"


def _robustness_note(analysis, inputs):
    if inputs is None:
        return ""
    parts = []
    imbalance = None
    for feature in analysis.qor_record["robustness"].features:
        if feature.feature_id == "F_CTS_BUF_IMBAL":
            imbalance = feature.value
    if imbalance is not None:
        parts.append(f"CTS Imbal: {_fmt(imbalance, 1)}")
    if inputs.corners:
        spread = max(c.setup_ws for c in inputs.corners) - min(c.setup_ws for c in inputs.corners)
        parts.append(f"PVT Spread: {spread:.2f}ns")
    return f"({', '.join(parts)})" if parts else ""
