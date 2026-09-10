"""Overall QoR score report for one workspace.

Reads current per-step ``analysis/qor_metrics.json`` files and scores them
with ``chipcompiler.engine.qor_scoring``. That module is the only scoring
rule table (fail thresholds, dimension weights, pass line, metric
selection). Studio uses the same scorer via the Engineering Snapshot
``qorAssessment``; this report does not keep a second copy of the rules.

This file owns CLI collection and presentation only: metric-file
normalization, DRC/LVS/RCX/STA flow-state gates, and the text report.
Cross-workspace trend, summary blocking-issue gates, and signoff-readiness
score eligibility stay on the Studio project dashboard.

Metrics already carry dimension (category), polarity (direction), and the
rating gate from tools/ecc/metrics.py::build_qor_metrics_payload.
"""

import dataclasses
import math
from pathlib import Path

from chipcompiler.data import StateEnum, StepEnum
from chipcompiler.data.step_dirs import STEP_DIRECTORIES
from chipcompiler.engine.qor_scoring import (
    DIMENSION_WEIGHTS,
    QOR_SCORE_THRESHOLD,
    QorScoringMetric,
    score_metric,
    score_qor,
)
from chipcompiler.utility.json import json_read

# GUI FlowStep label for each canonical step that owns a scored directory.
_STEP_ENUM_TO_LABEL = {
    StepEnum.SYNTHESIS.value: "Synth",
    StepEnum.FLOORPLAN.value: "Floor",
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

# GUI FlowStep labels in flow order, derived from the canonical
# step->directory mapping (lec/postRouteLec and the label-less TimingOpt
# step carry no scored directory, so they drop out).
FLOW_STEP_DIRS = {
    _STEP_ENUM_TO_LABEL[step]: directory
    for step, directory in STEP_DIRECTORIES.items()
    if step in _STEP_ENUM_TO_LABEL
}

FLOW_STEPS = tuple(FLOW_STEP_DIRS)

DIMENSION_LABELS = {
    "timing": "Timing",
    "power_integrity": "Power / IR / EM",
    "routability_physical": "Routability / Physical",
    "area_cost": "Area",
    "clock_robustness_dfm": "Clock / DFM",
    "runtime": "Runtime",
}

GATE_STEPS = ("DRC", "LVS", "RCX", "STA")

_ROLE_PRIORITY = {"final", "gate", "trend", "none"}


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
    """Parse a finite metric number; NaN/Infinity are invalid, not extreme."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str) and value.strip():
        try:
            number = float(value.replace(",", "").strip())
        except ValueError:
            return None
        return number if math.isfinite(number) else None
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


def score_record(record: QorMetricRecord) -> float | None:
    return score_metric(_scoring_metric(record))


def _scoring_metric(record: QorMetricRecord) -> QorScoringMetric:
    return QorScoringMetric(
        step=record.step,
        metric_id=record.metric_name,
        value=record.value,
        dimension=record.dimension,
        direction=record.polarity,
        scope=record.scope,
        corner=record.corner,
        project_role=record.project_role,
        rating_score=record.rating_score,
        payload=record,
    )


def _resolve_area_scoring_step(records, flow_steps_by_label) -> str | None:
    scored = [
        _scoring_metric(record)
        for record in records
        if record.rating_score
        and record.dimension == "area_cost"
        and flow_steps_by_label.get(record.step) == StateEnum.Success.value
    ]
    return score_qor(scored, flow_order=FLOW_STEPS).area_scoring_step


def _gate_status(flow_steps_by_label) -> str:
    # A pass verdict requires every gate step to be present and successful:
    # a successful DRC with LVS/RCX/STA absent is partial evidence, not a
    # pass.
    known = [step for step in GATE_STEPS if step in flow_steps_by_label]
    if not known:
        return "unavailable"
    states = {flow_steps_by_label[step] for step in known}
    if states & {StateEnum.Imcomplete.value, StateEnum.Invalid.value}:
        return "blocked"
    if states - {StateEnum.Success.value}:
        return "incomplete"
    if len(known) < len(GATE_STEPS):
        return "incomplete"
    return "pass"


def _flow_completion_state(states) -> str:
    """Classify a workspace's step-state set explicitly.

    Only an all-Success ledger completes a flow.
    """
    from chipcompiler.data.step import FINISHED_STEP_STATES

    values = list(states)
    if any(state in (StateEnum.Imcomplete.value, StateEnum.Invalid.value) for state in values):
        return "failed"
    if not values:
        return "not_started"
    if all(state in FINISHED_STEP_STATES for state in values):
        return "complete"
    if any(state == StateEnum.Ongoing.value for state in values):
        return "running"
    if all(state == StateEnum.Unstart.value for state in values):
        return "not_started"
    return "in_progress"


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


def _workspace_parameters(workspace, workspace_root: Path) -> dict:
    parameters = getattr(getattr(workspace, "parameters", None), "data", None)
    if isinstance(parameters, dict):
        return parameters
    legacy = json_read(workspace_root / "home" / "parameters.json")
    return legacy if isinstance(legacy, dict) else {}


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
        # Only currently successful steps score: invalidation keeps a step's
        # analysis outputs on disk, so without this gate a stale suffix would
        # report its obsolete metrics as current.
        if flow_steps_by_label.get(step) != StateEnum.Success.value:
            continue
        payload = json_read(workspace_root / dir_name / "analysis" / "qor_metrics.json")
        if not payload:
            continue
        analyzed_steps.append(step)
        records.extend(_normalize_metrics(step, payload))

    scoring = score_qor([_scoring_metric(record) for record in records], flow_order=FLOW_STEPS)
    scored = [
        dataclasses.replace(item.metric.payload, score=item.score) for item in scoring.metrics
    ]

    gate = _gate_status(flow_steps_by_label)
    flow_state = _flow_completion_state(flow_steps_by_label.values())

    parameters = _workspace_parameters(workspace, workspace_root)
    workspace_design = getattr(workspace, "design", None)
    design = (
        getattr(workspace_design, "name", "")
        or getattr(workspace, "name", "")
        or parameters.get("design")
        or parameters.get("Design")
        or ""
    )

    dimension_scores = [
        QorDimensionScore(
            dimension=dimension,
            label=DIMENSION_LABELS[dimension],
            weight=DIMENSION_WEIGHTS[dimension],
            score=scoring.dimensions[dimension][0],
            metric_count=scoring.dimensions[dimension][1],
        )
        for dimension in DIMENSION_WEIGHTS
        if dimension in scoring.dimensions
    ]
    absent = [
        DIMENSION_LABELS[dimension]
        for dimension in DIMENSION_WEIGHTS
        if dimension not in scoring.dimensions and DIMENSION_WEIGHTS[dimension] > 0
    ]

    return QorScoreReport(
        workspace=str(workspace_root),
        design=design,
        overall_score=scoring.overall_score,
        status=_workspace_status(flow_state, scoring.overall_score, gate),
        gate_status=gate,
        area_scoring_step=scoring.area_scoring_step,
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


def generate_qor_report(workspace, report=None) -> str:
    """Render the overall QoR score report as GUI-parity text.

    Pass a prebuilt *report* to render the exact snapshot the caller
    already collected instead of re-traversing the workspace.
    """
    report = report if report is not None else build_qor_report(workspace)
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
