"""Overall QoR score report for one workspace.

Python port of the ECOS Studio GUI scoring pipeline
(ecos/gui/apps/renderer/src/utils/projectQorTrend.ts), restricted to the
single-workspace view the CLI needs: normalize the per-step schema-v3
``analysis/qor_metrics.json`` records, select project-level records, score
each metric against the GUI fail thresholds, average per dimension, and
combine with the GUI dimension weights (deliberately NOT renormalized over
missing dimensions, matching GUI behavior). Trimmed relative to the GUI:
cross-workspace trend/regression analysis, summary blocking-issue gates, and
signoff-readiness score eligibility are project-dashboard concerns.

Report source of truth: metrics files already carry dimension (category),
polarity (direction), and the rating gate, written by
tools/ecc/metrics.py::build_qor_metrics_payload.
"""

import dataclasses
from pathlib import Path

from chipcompiler.data import StateEnum, StepEnum
from chipcompiler.utility.json import json_read

# GUI FlowStep labels in flow order, mapped to workspace step directories.
FLOW_STEP_DIRS = {
    "Synth": "Synthesis_yosys",
    "Floor": "Floorplan_ecc",
    "Fanout": "fixFanout_ecc",
    "Place": "place_dreamplace",
    "CTS": "CTS_ecc",
    "Legal": "legalization_dreamplace",
    "Route": "route_ecc",
    "DRC": "drc_ecc",
    "LVS": "lvs_ecc",
    "Filler": "filler_ecc",
    "RCX": "RCX_ecc",
    "STA": "sta_ecc",
    "Harden": "Harden_ecc",
}

FLOW_STEPS = tuple(FLOW_STEP_DIRS)

DIMENSION_WEIGHTS = {
    "timing": 0.35,
    "power_integrity": 0.25,
    "routability_physical": 0.2,
    "area_cost": 0.1,
    "clock_robustness_dfm": 0.1,
    "runtime": 0.0,
}

DIMENSION_LABELS = {
    "timing": "Timing",
    "power_integrity": "Power / IR / EM",
    "routability_physical": "Routability / Physical",
    "area_cost": "Area",
    "clock_robustness_dfm": "Clock / DFM",
    "runtime": "Runtime",
}

METRIC_FAIL_VALUES = {
    "drc_count": 10,
    "lvs_count": 10,
    "route_wirelength": 6000,
    "route_via_count": 2000,
    "cts_buffer_count": 20,
    "cts_buffer_area": 40,
    "clock_wirelength": 400000,
    "cts_clock_wirelength_max": 100000,
    "cts_clock_tree_max_level": 20,
    "die_area": 3000,
    "core_area": 2500,
    "core_utilization": 0.85,
    "synthesis_cell_area": 3000,
    "fanout_max": 100,
    "place_hpwl": 10000,
    "place_grwl": 12000,
    "place_flute_wirelength": 10000,
    "place_congestion_egr_overflow_total": 100,
    "place_congestion_egr_overflow_max": 20,
    "place_rudy_utilization_max": 1,
    "place_lutrudy_utilization_max": 1,
    "route_dr_total_violation_count": 50,
    "route_dr_total_patch_count": 100,
    "route_dr_total_wirelength": 6000,
    "route_dr_total_via_count": 2000,
    "route_la_total_overflow": 100,
    "rcx_missing_corner_count": 9,
    "sta_setup_wns": -0.2,
    "sta_setup_tns": -1,
    "sta_hold_wns": -0.2,
    "sta_hold_tns": -1,
    "sta_frequency_mhz": 100,
    "sta_setup_violation_count": 1,
    "sta_hold_violation_count": 1,
    "sta_missing_corner_count": 1,
    "harden_artifact_missing_count": 6,
}

SLACK_METRICS = {"sta_setup_wns", "sta_setup_tns", "sta_hold_wns", "sta_hold_tns"}
CORE_UTILIZATION_TARGET = (0.45, 0.70)

#: The 0-100 line separating the GUI pass/fail presentation.
QOR_SCORE_THRESHOLD = 60

GATE_STEPS = ("DRC", "LVS", "RCX", "STA")

_ROLE_PRIORITY = {"final": 0, "gate": 1, "trend": 2, "none": 3}


@dataclasses.dataclass(frozen=True)
class QorMetricRecord:
    step: str
    metric_name: str
    display_name: str
    value: float
    unit: str = ""
    dimension: str = ""
    polarity: str = ""
    scope: str = ""
    corner: str | None = None
    project_role: str = "none"
    step_role: str = "detail"
    rating_score: bool = False
    rating_gate: bool = False
    score: float | None = None


@dataclasses.dataclass(frozen=True)
class QorDimensionScore:
    dimension: str
    label: str
    weight: float
    score: float
    metric_count: int


@dataclasses.dataclass
class QorScoreReport:
    workspace: str = ""
    design: str = ""
    overall_score: float | None = None
    status: str = "Blocked"
    gate_status: str = "unavailable"
    area_scoring_step: str | None = None
    dimension_scores: list = dataclasses.field(default_factory=list)
    metrics: list = dataclasses.field(default_factory=list)
    absent_dimensions: list = dataclasses.field(default_factory=list)
    analyzed_steps: list = dataclasses.field(default_factory=list)


# ---------------------------------------------------------------------------
# Normalization (port of normalizeQorMetrics)
# ---------------------------------------------------------------------------


def _flexible_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.replace(",", "").strip())
        except ValueError:
            return None
    return None


def _string_value(value):
    return value if isinstance(value, str) and value else None


def _valid_rating(value) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("gate"), bool)
        and isinstance(value.get("score"), bool)
        and isinstance(value.get("trend"), bool)
    )


def _normalize_metrics(step: str, payload: dict) -> list[QorMetricRecord]:
    if not isinstance(payload, dict):
        return []
    if payload.get("schema_version") != 3 or not isinstance(payload.get("metrics"), list):
        return []
    records = []
    for raw in payload["metrics"]:
        if not isinstance(raw, dict):
            continue
        value = _flexible_number(raw.get("value"))
        dimension = _string_value(raw.get("category"))
        polarity = _string_value(raw.get("direction"))
        scope = _string_value(raw.get("scope"))
        project_role = _string_value(raw.get("project_role"))
        step_role = _string_value(raw.get("step_role"))
        metric_name = _string_value(raw.get("id"))
        if (
            metric_name is None
            or value is None
            or dimension not in DIMENSION_WEIGHTS
            or polarity not in ("higher_is_better", "lower_is_better", "target_range", "trend_only")
            or scope is None
            or project_role not in _ROLE_PRIORITY
            or step_role not in ("primary", "secondary", "detail", "hidden")
            or not _valid_rating(raw.get("rating"))
        ):
            continue
        corner = raw.get("corner")
        corner = corner if isinstance(corner, str) else None
        records.append(
            QorMetricRecord(
                step=step,
                metric_name=metric_name,
                display_name=_string_value(raw.get("display_name")) or metric_name,
                value=value,
                unit=_string_value(raw.get("unit")) or "",
                dimension=dimension,
                polarity=polarity,
                scope=scope,
                corner=corner,
                project_role=project_role,
                step_role=step_role,
                rating_score=raw["rating"]["score"],
                rating_gate=raw["rating"]["gate"],
            )
        )
    return records


# ---------------------------------------------------------------------------
# Scoring (port of scoreRecord / buildDimensionScores / weightedOverallScore)
# ---------------------------------------------------------------------------


def _clamp_score(score: float) -> float:
    return max(0.0, min(100.0, score))


def _round_score(score: float) -> float:
    return round(score, 1)


def _score_target_range(value: float, min_target: float, max_target: float, fail: float) -> float:
    if min_target <= value <= max_target:
        return 100.0
    if value < min_target:
        return _clamp_score(100 * value / min_target)
    return _clamp_score(100 * (fail - value) / (fail - max_target))


def score_record(record: QorMetricRecord) -> float | None:
    if record.polarity == "trend_only":
        return None
    if record.metric_name not in METRIC_FAIL_VALUES:
        return None

    if record.metric_name in SLACK_METRICS:
        fail = METRIC_FAIL_VALUES[record.metric_name]
        if fail >= 0:
            return None
        if record.value >= 0:
            return 100.0
        return _clamp_score(100 * (record.value - fail) / -fail)

    if record.polarity == "target_range":
        if record.metric_name == "core_utilization":
            return _score_target_range(
                record.value, *CORE_UTILIZATION_TARGET, METRIC_FAIL_VALUES["core_utilization"]
            )
        return None

    fail = METRIC_FAIL_VALUES[record.metric_name]
    if fail <= 0:
        return None
    if record.polarity == "lower_is_better":
        return _clamp_score(100 * (fail - record.value) / fail)
    return _clamp_score(100 * record.value / fail)


def _record_key(record: QorMetricRecord) -> tuple:
    return (record.metric_name, record.scope, record.corner or "")


def _select_project_records(records, area_scoring_step) -> list[QorMetricRecord]:
    selected: dict[tuple, QorMetricRecord] = {}
    for record in records:
        if record.project_role == "none":
            continue
        if record.dimension == "area_cost" and record.step != area_scoring_step:
            continue
        current = selected.get(_record_key(record))
        if current is None or _selection_rank(record) < _selection_rank(current):
            selected[_record_key(record)] = record
    return sorted(selected.values(), key=lambda r: r.metric_name)


def _selection_rank(record: QorMetricRecord) -> tuple:
    return (_ROLE_PRIORITY[record.project_role], -FLOW_STEPS.index(record.step))


def _resolve_area_scoring_step(records, flow_steps_by_label) -> str | None:
    for step in reversed(FLOW_STEPS):
        if flow_steps_by_label.get(step) != StateEnum.Success.value:
            continue
        if any(r.step == step and r.dimension == "area_cost" and r.rating_score for r in records):
            return step
    return None


def _gate_status(flow_steps_by_label) -> str:
    known = [step for step in GATE_STEPS if step in flow_steps_by_label]
    if not known:
        return "unavailable"
    states = {flow_steps_by_label[step] for step in known}
    if states & {StateEnum.Imcomplete.value, StateEnum.Invalid.value}:
        return "blocked"
    if states - {StateEnum.Success.value}:
        return "incomplete"
    return "pass"


def _workspace_status(flow_state: str, score: float | None, gate: str) -> str:
    if flow_state == "failed":
        return "Red"
    if flow_state in ("running", "in_progress", "not_started"):
        return "Blocked"
    if gate == "blocked":
        return "Orange"
    if gate == "incomplete":
        return "Yellow"
    if score is None:
        return "Blocked"
    if score >= 40:
        return "Green"
    if score >= 25:
        return "Yellow"
    if score >= 10:
        return "Orange"
    return "Red"


def _weighted_overall(dimension_scores: dict) -> float | None:
    weighted_total = 0.0
    used_weight = 0.0
    for dimension, score in dimension_scores.items():
        weight = DIMENSION_WEIGHTS[dimension]
        if weight <= 0:
            continue
        weighted_total += score * weight
        used_weight += weight
    if used_weight == 0:
        return None
    # GUI behavior: no renormalization over missing dimensions.
    return weighted_total


# ---------------------------------------------------------------------------
# Workspace collection and rendering
# ---------------------------------------------------------------------------


def _flow_states(workspace) -> dict[str, str]:
    flow = getattr(workspace, "flow", None)
    data = getattr(flow, "data", None)
    if not isinstance(data, dict) or not data:
        # load_workspace leaves flow.data empty; the persisted file is the
        # source of truth (same fallback the signoff collector uses).
        data = json_read(Path(workspace.directory or "") / "home" / "flow.json")
    steps = data.get("steps") if isinstance(data, dict) else None
    states = {}
    if isinstance(steps, list):
        for raw in steps:
            if isinstance(raw, dict) and isinstance(raw.get("name"), str):
                states[raw["name"]] = raw.get("state") if isinstance(raw.get("state"), str) else ""
    return states


_STEP_ENUM_TO_LABEL = {
    StepEnum.SYNTHESIS.value: "Synth",
    StepEnum.FLOORPLAN.value: "Floor",
    StepEnum.NETLIST_OPT.value: "Fanout",
    StepEnum.PLACEMENT.value: "Place",
    StepEnum.CTS.value: "CTS",
    StepEnum.LEGALIZATION.value: "Legal",
    StepEnum.ROUTING.value: "Route",
    StepEnum.DRC.value: "DRC",
    StepEnum.LVS.value: "LVS",
    StepEnum.FILLER.value: "Filler",
    StepEnum.RCX.value: "RCX",
    StepEnum.STA.value: "STA",
    StepEnum.HARDEN.value: "Harden",
}


def build_qor_report(workspace) -> QorScoreReport:
    """Score one workspace's current analysis outputs the way the GUI does."""
    workspace_root = Path(workspace.directory or "")
    raw_states = _flow_states(workspace)
    flow_steps_by_label = {
        _STEP_ENUM_TO_LABEL.get(name, name): state for name, state in raw_states.items()
    }

    records: list[QorMetricRecord] = []
    analyzed_steps = []
    for step, dir_name in FLOW_STEP_DIRS.items():
        payload = json_read(workspace_root / dir_name / "analysis" / "qor_metrics.json")
        if not payload:
            continue
        analyzed_steps.append(step)
        records.extend(_normalize_metrics(step, payload))

    area_scoring_step = _resolve_area_scoring_step(records, flow_steps_by_label)
    project_records = _select_project_records(records, area_scoring_step)

    scored: list[QorMetricRecord] = []
    by_dimension: dict[str, list[float]] = {}
    for record in project_records:
        # GUI gate: only rating.score records feed dimension averages; the
        # rest stay in the table marked as trend-only.
        score = score_record(record) if record.rating_score else None
        scored.append(dataclasses.replace(record, score=score))
        if score is not None:
            by_dimension.setdefault(record.dimension, []).append(score)

    dimension_averages = {
        dimension: _round_score(sum(scores) / len(scores))
        for dimension, scores in by_dimension.items()
    }
    overall = _weighted_overall(dimension_averages)
    overall_score = _round_score(overall) if overall is not None else None

    gate = _gate_status(flow_steps_by_label)
    flow_state = (
        "failed"
        if any(
            state in (StateEnum.Imcomplete.value, StateEnum.Invalid.value)
            for state in flow_steps_by_label.values()
        )
        else ("complete" if flow_steps_by_label else "not_started")
    )

    parameters = json_read(workspace_root / "home" / "parameters.json")
    design = getattr(workspace, "name", "") or (parameters or {}).get("Design") or ""

    dimension_scores = [
        QorDimensionScore(
            dimension=dimension,
            label=DIMENSION_LABELS[dimension],
            weight=DIMENSION_WEIGHTS[dimension],
            score=dimension_averages[dimension],
            metric_count=len(by_dimension[dimension]),
        )
        for dimension in DIMENSION_WEIGHTS
        if dimension in dimension_averages
    ]
    absent = [
        DIMENSION_LABELS[dimension]
        for dimension in DIMENSION_WEIGHTS
        if dimension not in dimension_averages and DIMENSION_WEIGHTS[dimension] > 0
    ]

    return QorScoreReport(
        workspace=str(workspace_root),
        design=design,
        overall_score=overall_score,
        status=_workspace_status(flow_state, overall_score, gate),
        gate_status=gate,
        area_scoring_step=area_scoring_step,
        dimension_scores=dimension_scores,
        metrics=scored,
        absent_dimensions=absent,
        analyzed_steps=analyzed_steps,
    )


WIDTH = 78


def _pad(text: str, width: int) -> str:
    if len(text) >= width:
        return text
    return text + " " * (width - len(text))


def _fmt(value, unit: str = "") -> str:
    if value is None:
        return "—"
    text = f"{value:g}" if isinstance(value, float) else str(value)
    return f"{text} {unit}".rstrip() if unit else text


def generate_qor_report(workspace) -> str:
    """Render the overall QoR score report as GUI-parity text."""
    report = build_qor_report(workspace)
    lines: list[str] = []
    score_text = f"{report.overall_score:g}" if report.overall_score is not None else "—"
    verdict = (
        "PASS"
        if report.overall_score is not None and report.overall_score >= QOR_SCORE_THRESHOLD
        else "BELOW THRESHOLD"
        if report.overall_score is not None
        else "NOT RATED"
    )
    title = f"  ECC QOR OVERALL SCORE — {score_text}/100 ({verdict})  "
    side = max(0, (WIDTH - len(title)) // 2)
    lines.append("=" * side + title + "=" * (WIDTH - side - len(title)))
    lines.append(f"Design              : {report.design or '—'}")
    lines.append(f"Workspace           : {report.workspace}")
    lines.append(f"Flow status         : {report.status}   gate: {report.gate_status}")
    if report.area_scoring_step:
        lines.append(f"Area scoring step   : {report.area_scoring_step}")
    lines.append(f"Analyzed steps      : {', '.join(report.analyzed_steps) or '—'}")
    lines.append(f"Pass threshold      : {QOR_SCORE_THRESHOLD} (weights not renormalized)")
    lines.append("=" * WIDTH)
    lines.append("")

    lines.append("[ DIMENSION SCORES ]")
    lines.append("-" * WIDTH)
    lines.append(f"  {_pad('Dimension', 24)} {_pad('Score', 9)} {_pad('Weight', 8)} Metrics")
    for dimension in report.dimension_scores:
        lines.append(
            f"  {_pad(dimension.label, 24)} {_pad(f'{dimension.score:g}', 9)}"
            f" {_pad(f'{dimension.weight:g}', 8)} {dimension.metric_count}"
        )
    if report.absent_dimensions:
        lines.append("")
        lines.append("  Absent dimensions (no scoreable metrics):")
        for label in report.absent_dimensions:
            lines.append(f"    - {label}")
    lines.append("")

    lines.append("[ METRIC SCORES ]")
    lines.append("-" * WIDTH)
    lines.append(
        f"  {_pad('Metric', 34)} {_pad('Step', 8)} {_pad('Corner', 12)} {_pad('Value', 14)} Score"
    )
    lines.append("  " + "-" * (WIDTH - 4))
    for record in report.metrics:
        corner = record.corner or ""
        value = _fmt(record.value, record.unit)
        score = f"{record.score:g}" if record.score is not None else "trend"
        lines.append(
            f"  {_pad(record.display_name, 34)} {_pad(record.step, 8)} {_pad(corner, 12)}"
            f" {_pad(value, 14)} {score}"
        )
    if not report.metrics:
        lines.append("  (no project-level QoR metrics available)")

    lines.append("")
    lines.append("=" * WIDTH)
    lines.append("END OF QOR REPORT")
    return "\n".join(lines)
