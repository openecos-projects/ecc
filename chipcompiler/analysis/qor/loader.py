"""Workspace reader for the QoR engine.

Reads only persisted artifacts; it never mutates workspace state and
never treats a missing report as zero. Steps count toward analysis only
when their ledger state is Success — invalidation keeps old outputs on
disk, and stale suffixes must not report obsolete metrics as current.
"""

import dataclasses
from math import isfinite
from pathlib import Path

from chipcompiler.analysis.qor.metric_registry import SCORED_STEP_VALUES
from chipcompiler.data import StateEnum, StepEnum
from chipcompiler.data.step_dirs import STEP_DIRECTORIES
from chipcompiler.tools.ecc.sta_qor import (
    POST_SYNTHESIS_STA_CORNER,
    STA_POWER_SUMMARY_FILENAME,
    configured_sta_artifact_directories,
    read_sta_power_summary_json,
    read_sta_qor_summary,
)
from chipcompiler.utility.json import json_read

_ROLE_PRIORITY = {"final": 0, "gate": 1, "trend": 2, "none": 3}

_STA_FEATURE_DIR = STEP_DIRECTORIES[StepEnum.STA.value] + "/feature"


@dataclasses.dataclass
class MetricRecord:
    metric_id: str
    value: float
    unit: str
    step: str  # step enum value
    project_role: str
    corner: str | None
    source: dict
    scope: str | None = None
    endpoint_population: float | None = None


@dataclasses.dataclass(frozen=True)
class CornerSlack:
    corner: str
    setup_ws: float
    hold_ws: float | None
    setup_nvp: int | None
    hold_nvp: int | None


@dataclasses.dataclass
class QorInputs:
    design: str = ""
    workspace_path: str = ""
    flow_states: dict = dataclasses.field(default_factory=dict)
    metrics: dict = dataclasses.field(default_factory=dict)  # metric id -> MetricRecord
    analyzed_steps: list = dataclasses.field(default_factory=list)
    parse_failures: int = 0
    invalid_selector_count: int = 0
    corners: list = dataclasses.field(default_factory=list)  # CornerSlack records
    sta_expected_corners: float | None = None
    rcx_spef_count: float | None = None
    rcx_expected_spef: float | None = None
    power_total_uw: float | None = None
    power_source_path: str | None = None
    power_source_kind: str | None = None
    power_corner: str | None = None
    sta_setup_only: bool = False
    tclk_ns: float | None = None
    profile: str = "balanced"
    power_budget_uw: float | None = None
    config_warnings: list = dataclasses.field(default_factory=list)

    def value(self, metric_id):
        record = self.metrics.get(metric_id)
        return record.value if record is not None else None

    def source_path(self, metric_id):
        record = self.metrics.get(metric_id)
        if record is None or not isinstance(record.source, dict):
            return ""
        return str(record.source.get("path", ""))

    def step_state(self, step_value):
        return self.flow_states.get(step_value)


def _flow_states(workspace, workspace_root: Path) -> dict:
    flow = getattr(workspace, "flow", None)
    data = getattr(flow, "data", None)
    if not isinstance(data, dict) or not data:
        # load_workspace leaves flow.data empty; the persisted file is the
        # source of truth (same fallback the signoff collector uses).
        data = json_read(workspace_root / "home" / "flow.json")
    steps = data.get("steps") if isinstance(data, dict) else None
    states = {}
    if isinstance(steps, list):
        for raw in steps:
            if isinstance(raw, dict) and isinstance(raw.get("name"), str):
                state = raw.get("state")
                states[raw["name"]] = state if isinstance(state, str) else ""
    return states


def _parameters(workspace, workspace_root: Path) -> dict:
    parameters = getattr(getattr(workspace, "parameters", None), "data", None)
    if isinstance(parameters, dict):
        return parameters
    legacy = json_read(workspace_root / "home" / "parameters.json")
    return legacy if isinstance(legacy, dict) else {}


def _payload_metrics(payload: dict) -> list:
    if not isinstance(payload, dict):
        return []
    if payload.get("schema_version") != 3 or not isinstance(payload.get("metrics"), list):
        return []
    return [raw for raw in payload["metrics"] if isinstance(raw, dict)]


def _select_metrics(step_payloads: list) -> dict:
    """Project-level selection: final > gate > trend, later step wins."""
    selected: dict = {}
    for index, (step_value, records) in enumerate(step_payloads):
        for raw in records:
            metric_id = raw.get("id")
            value = raw.get("value")
            if not isinstance(metric_id, str) or not metric_id:
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
            ):
                continue
            role = raw.get("project_role")
            if role not in _ROLE_PRIORITY or role == "none":
                continue
            record = MetricRecord(
                metric_id=metric_id,
                value=float(value),
                unit=raw.get("unit") if isinstance(raw.get("unit"), str) else "",
                step=step_value,
                project_role=role,
                corner=raw.get("corner") if isinstance(raw.get("corner"), str) else None,
                source=raw.get("source") if isinstance(raw.get("source"), dict) else {},
                scope=raw.get("scope") if isinstance(raw.get("scope"), str) else None,
                endpoint_population=(
                    float(raw["endpoint_population"])
                    if isinstance(raw.get("endpoint_population"), (int, float))
                    and not isinstance(raw.get("endpoint_population"), bool)
                    else None
                ),
            )
            rank = (_ROLE_PRIORITY[role], -index)
            current = selected.get(metric_id)
            if current is None or rank < current[0]:
                selected[metric_id] = (rank, record)
    return {metric_id: rank_record[1] for metric_id, rank_record in selected.items()}


def _corner_slack(workspace, workspace_root: Path, flow_states: dict) -> tuple[list, bool]:
    if flow_states.get(StepEnum.STA.value) != StateEnum.Success.value:
        return [], False
    corners = []
    feature_root = workspace_root / _STA_FEATURE_DIR
    if not feature_root.is_dir():
        return corners, False

    configured = configured_sta_artifact_directories(workspace, feature_root)
    if configured:
        candidates = [(label, path / "qor_summary.json") for label, path in configured]
    else:
        # Test stand-ins may omit workspace.config. Real workspaces are always
        # constrained by configured STA directories above.
        candidates = [
            (path.parts[-3], path) for path in sorted(feature_root.glob("*/*/qor_summary.json"))
        ]

    setup_only = False
    for corner, path in candidates:
        summary = read_sta_qor_summary(corner, path, require_hold=False)
        if summary is None:
            continue
        setup_only = setup_only or summary.hold_wns is None
        corners.append(
            CornerSlack(
                corner=summary.corner,
                setup_ws=summary.setup_wns,
                hold_ws=summary.hold_wns,
                setup_nvp=summary.setup_nvp,
                hold_nvp=summary.hold_nvp,
            )
        )
    return corners, setup_only


def _power_summary(workspace, workspace_root: Path, flow_states: dict):
    """Select the worst available signoff power, with synthesis fallback."""
    if flow_states.get(StepEnum.STA.value) == StateEnum.Success.value:
        feature_root = workspace_root / _STA_FEATURE_DIR
        totals = []
        configured = configured_sta_artifact_directories(workspace, feature_root)
        if configured:
            candidates = configured
        else:
            # Keep report generation useful for fixtures and workspaces whose
            # STA config is unavailable: only persisted feature artifacts are
            # considered, and the selected path remains auditable.
            candidates = [
                (
                    path.parent.relative_to(feature_root).as_posix(),
                    path.parent,
                )
                for path in sorted(feature_root.glob("*/*/" + STA_POWER_SUMMARY_FILENAME))
            ]
        for corner, directory in candidates:
            path = directory / STA_POWER_SUMMARY_FILENAME
            summary = read_sta_power_summary_json(path)
            if summary is not None:
                totals.append((summary.dynamic_uw + summary.leakage_uw, path, corner))
        if totals:
            total, path, corner = max(totals, key=lambda item: item[0])
            return total, path, "signoff", corner

    if flow_states.get(StepEnum.SYNTHESIS.value) == StateEnum.Success.value:
        path = (
            workspace_root
            / STEP_DIRECTORIES[StepEnum.SYNTHESIS.value]
            / "feature"
            / POST_SYNTHESIS_STA_CORNER
            / STA_POWER_SUMMARY_FILENAME
        )
        summary = read_sta_power_summary_json(path)
        if summary is not None:
            return (
                summary.dynamic_uw + summary.leakage_uw,
                path,
                "synthesis",
                POST_SYNTHESIS_STA_CORNER,
            )
    return None, None, None, None


def _resolve_parameters(parameters: dict, warnings: list) -> tuple:
    """Resolve (tclk_ns, profile, power_budget_uw) from flat parameters."""
    tclk_ns = None
    frequency_max = parameters.get("frequency_max")
    if isinstance(frequency_max, (int, float)) and not isinstance(frequency_max, bool):
        if frequency_max > 0:
            tclk_ns = 1000.0 / float(frequency_max)
        else:
            warnings.append("frequency_max must be positive; timing quality is UNKNOWN")

    profile = parameters.get("qor_profile")
    if profile is None or profile == "":
        profile = "balanced"
    elif profile not in ("balanced", "timing_critical", "low_power", "area_optimized"):
        warnings.append(f"unknown qor_profile {profile!r}; using 'balanced'")
        profile = "balanced"

    budget = parameters.get("qor_power_budget_w")
    power_budget_uw = None
    if budget is not None:
        if isinstance(budget, (int, float)) and not isinstance(budget, bool) and budget > 0:
            power_budget_uw = float(budget) * 1e6
        else:
            warnings.append("qor_power_budget_w must be a positive number; power quality UNKNOWN")
    return tclk_ns, profile, power_budget_uw


def load_workspace_qor_inputs(workspace) -> QorInputs:
    workspace_root = Path(workspace.directory or "")
    design = getattr(getattr(workspace, "design", None), "name", "") or getattr(
        workspace, "name", ""
    )
    if not design:
        parameters = _parameters(workspace, workspace_root)
        design = parameters.get("design") or parameters.get("Design") or ""

    warnings: list = []
    parameters = _parameters(workspace, workspace_root)
    tclk_ns, profile, power_budget_uw = _resolve_parameters(parameters, warnings)
    flow_states = _flow_states(workspace, workspace_root)

    step_payloads: list = []
    analyzed_steps: list = []
    parse_failures = 0
    invalid_selector_count = 0
    for step_value in SCORED_STEP_VALUES:
        if flow_states.get(step_value) != StateEnum.Success.value:
            continue
        directory = STEP_DIRECTORIES[step_value]
        payload = json_read(workspace_root / directory / "analysis" / "qor_metrics.json")
        records = _payload_metrics(payload)
        if payload is None or not records:
            parse_failures += 1
            continue
        analyzed_steps.append(step_value)
        integrity = payload.get("integrity")
        if isinstance(integrity, dict):
            invalid_selector_count += len(integrity.get("invalid_metric_source_ids") or [])
            invalid_selector_count += len(integrity.get("invalid_detail_ids") or [])
        step_payloads.append((step_value, records))

    metrics = _select_metrics(step_payloads)

    def _metric_value(metric_id: str) -> float | None:
        record = metrics.get(metric_id)
        return record.value if record is not None else None

    power_total_uw, power_source, power_source_kind, power_corner = _power_summary(
        workspace, workspace_root, flow_states
    )
    corners, sta_setup_only = _corner_slack(workspace, workspace_root, flow_states)

    return QorInputs(
        design=design,
        workspace_path=str(workspace_root),
        flow_states=flow_states,
        metrics=metrics,
        analyzed_steps=analyzed_steps,
        parse_failures=parse_failures,
        invalid_selector_count=invalid_selector_count,
        corners=corners,
        sta_expected_corners=_metric_value("sta_expected_corner_count"),
        rcx_spef_count=_metric_value("rcx_spef_file_count"),
        rcx_expected_spef=_metric_value("rcx_expected_corner_count"),
        power_total_uw=power_total_uw,
        power_source_path=str(power_source) if power_source is not None else None,
        power_source_kind=power_source_kind,
        power_corner=power_corner,
        sta_setup_only=sta_setup_only,
        tclk_ns=tclk_ns,
        profile=profile,
        power_budget_uw=power_budget_uw,
        config_warnings=warnings,
    )
