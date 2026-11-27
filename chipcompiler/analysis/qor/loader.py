"""Workspace reader for the QoR engine.

Reads only persisted artifacts; it never mutates workspace state and
never treats a missing report as zero. Steps count toward analysis only
when their ledger state is Success — invalidation keeps old outputs on
disk, and stale suffixes must not report obsolete metrics as current.
"""

import dataclasses
from csv import reader as csv_reader
from math import isfinite
from pathlib import Path
from typing import cast

from chipcompiler.analysis.qor.gate_catalog import gate_metric_ids
from chipcompiler.analysis.qor.metric_registry import SCORED_STEP_VALUES, metric_range_violation
from chipcompiler.data import StateEnum, StepEnum
from chipcompiler.data.flow.document import FlowStepEntry
from chipcompiler.data.step import StepDirectories
from chipcompiler.tools.ecc.power_artifacts import power_step_path
from chipcompiler.tools.ecc.sta_qor import (
    POST_SYNTHESIS_STA_CORNER,
    STA_POWER_SUMMARY_FILENAME,
    configured_sta_artifact_directories,
    read_power_step_summary_json,
    read_sta_power_summary_json,
    read_sta_qor_summary,
)
from chipcompiler.utility.json import JsonObject, finite_number, json_read
from chipcompiler.utility.path import path_is_within

_ROLE_PRIORITY = {"final": 0, "gate": 1, "trend": 2, "none": 3}


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
    sta_corner_parse_failures: int = 0
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
    # Global-route union overflow grid read from the placement EGR map CSV:
    # total GCell count, GCells with positive overflow, and the CSV path.
    egr_gcell_count: int | None = None
    egr_overflowed_gcell_count: int | None = None
    egr_grid_source_path: str | None = None

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


def _flow_records(workspace, workspace_root: Path) -> list[FlowStepEntry]:
    flow = getattr(workspace, "flow", None)
    data = getattr(flow, "data", None)
    if not isinstance(data, dict) or not data:
        # load_workspace leaves flow.data empty; the persisted ledger is the
        # source of truth and enforces the current schema.
        from chipcompiler.data.flow.document import load_flow_document

        data = load_flow_document(workspace_root / "home" / "flow.json")
    steps = data.get("steps") if isinstance(data, dict) else None
    if not isinstance(steps, list):
        return []
    return [
        cast(FlowStepEntry, raw)
        for raw in steps
        if isinstance(raw, dict) and isinstance(raw.get("name"), str)
    ]


def _flow_states(records: list[FlowStepEntry]) -> dict:
    states = {}
    for raw in records:
        state = raw.get("state")
        states[raw["name"]] = state if isinstance(state, str) else ""
    return states


def _parameters(workspace, workspace_root: Path) -> dict:
    parameters = getattr(getattr(workspace, "parameters", None), "data", None)
    if isinstance(parameters, dict):
        return parameters
    from chipcompiler.data.workspace.config import load_workspace_config

    try:
        return load_workspace_config(workspace_root)
    except (OSError, ValueError):
        return {}


def _payload_metrics(payload: dict) -> list:
    if not isinstance(payload, dict):
        return []
    if payload.get("schema_version") != 3 or not isinstance(payload.get("metrics"), list):
        return []
    return [raw for raw in payload["metrics"] if isinstance(raw, dict)]


# Evidence may be written a moment after the cached metrics; allow clock/fs granularity.
_EVIDENCE_MTIME_TOLERANCE_S = 2.0


def _evidence_problem(step_dir: Path, cache: Path, raw: dict) -> str | None:
    """Why a gate metric's evidence artifact cannot back the cached value, or None.

    The artifact is the metric's own ``source.path`` (relative to the step
    directory). It must still exist and must not be newer than the cache.
    """
    source = raw.get("source")
    rel = source.get("path") if isinstance(source, dict) else None
    if not isinstance(rel, str) or not rel:
        return "no evidence path recorded"
    if Path(rel).is_absolute():
        return f"invalid evidence path: {rel}"
    artifact = step_dir / rel
    if not path_is_within(artifact, step_dir):
        return f"invalid evidence path: {rel}"
    if not artifact.is_file():
        return f"evidence artifact missing: {artifact}"
    try:
        artifact_mtime = artifact.stat().st_mtime
        cache_mtime = cache.stat().st_mtime
    except OSError:
        return f"evidence artifact missing: {artifact}"
    if artifact_mtime > cache_mtime + _EVIDENCE_MTIME_TOLERANCE_S:
        return f"evidence artifact newer than cached metrics (stale cache): {artifact}"
    return None


def _drop_unverified_gate_metrics(
    step_dir: Path, cache: Path, records: list, warnings: list
) -> list:
    """Remove gate metrics whose evidence is gone or changed; their gates become UNKNOWN."""
    gate_ids = gate_metric_ids()
    kept = []
    for raw in records:
        problem = _evidence_problem(step_dir, cache, raw) if raw.get("id") in gate_ids else None
        if problem is None:
            kept.append(raw)
        else:
            warnings.append(f"{raw['id']}: {problem}; gate is UNKNOWN")
    return kept


def _select_metrics(step_payloads: list, warnings: list | None = None) -> dict:
    """Project-level selection: final > gate > trend, later step wins.

    Records outside the registry's physical range are dropped (the metric
    becomes UNKNOWN downstream) and reported through ``warnings``.
    Two records with the same metric id inside a step payload are duplicates.
    Identical duplicates are harmless; conflicting ones within the step leave
    that metric unknown unless a later step supplies a higher-ranked record,
    matching ``QorMetrics`` in the step runners.
    """
    selected: dict = {}
    conflicted: dict = {}
    for index, (step_value, records) in enumerate(step_payloads):
        step_values: dict[str, float] = {}
        step_conflicts: dict[str, tuple[float, float]] = {}
        step_candidates: dict[str, tuple[tuple[int, int], MetricRecord]] = {}
        for raw in records:
            metric_id = raw.get("id")
            num = finite_number(raw.get("value"))
            if not isinstance(metric_id, str) or not metric_id or num is None:
                continue
            value = float(num)
            # Track duplicates before range filtering so an invalid entry
            # still conflicts with any differing record in the same step.
            first = step_values.setdefault(metric_id, value)
            if value != first and metric_id not in step_conflicts:
                step_conflicts[metric_id] = (first, value)
            violation = metric_range_violation(metric_id, value)
            if violation is not None:
                message = (
                    f"{metric_id}={raw.get('value')!r} is out of range ({violation}); "
                    "metric treated as UNKNOWN"
                )
                if warnings is not None and message not in warnings:
                    warnings.append(message)
                continue
            role = raw.get("project_role")
            if role not in _ROLE_PRIORITY or role == "none":
                continue
            fields = JsonObject(raw)
            ep = finite_number(raw.get("endpoint_population"))
            record = MetricRecord(
                metric_id=metric_id,
                value=value,
                unit=fields.get_str("unit"),
                step=step_value,
                project_role=role,
                corner=fields.get_str("corner", None),
                source=dict(fields.get_obj("source")),
                scope=fields.get_str("scope", None),
                endpoint_population=float(ep) if ep is not None else None,
            )
            rank = (_ROLE_PRIORITY[role], -index)
            best = step_candidates.get(metric_id)
            if best is None or rank < best[0]:
                step_candidates[metric_id] = (rank, record)

        for metric_id, (rank, record) in step_candidates.items():
            current = selected.get(metric_id)
            if current is None or rank < current[0]:
                selected[metric_id] = (rank, record)
                if metric_id in step_conflicts:
                    conflicted[metric_id] = (step_value, *step_conflicts[metric_id])
                else:
                    conflicted.pop(metric_id, None)
    for metric_id, (step_value, first, other) in conflicted.items():
        del selected[metric_id]
        if warnings is not None:
            warnings.append(
                f"duplicate conflicting records for {metric_id} in {step_value} "
                f"({first} vs {other}); metric treated as UNKNOWN"
            )
    return {metric_id: rank_record[1] for metric_id, rank_record in selected.items()}


def _corner_slack(
    workspace, directories: StepDirectories, flow_states: dict
) -> tuple[list, bool, int]:
    if flow_states.get(StepEnum.STA.value) != StateEnum.Success.value:
        return [], False, 0
    corners = []
    feature_root = directories.path(StepEnum.STA.value) / "feature"
    if not feature_root.is_dir():
        return corners, False, 0

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
    parse_failures = 0
    for corner, path in candidates:
        summary = read_sta_qor_summary(corner, path, require_hold=False)
        if summary is None:
            if path.is_file():
                parse_failures += 1
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
    return corners, setup_only, parse_failures


def _power_summary(workspace, directories: StepDirectories, flow_states: dict):
    """Select signoff power from the current power_analysis or synthesis artifact."""
    power_state = flow_states.get(StepEnum.POWER_ANALYSIS.value)
    if power_state == StateEnum.Success.value:
        power_directory = directories.path(StepEnum.POWER_ANALYSIS.value)
        feature_dir = power_directory / "feature"
        path = power_step_path(feature_dir)
        summary = read_power_step_summary_json(path)
        if summary is not None:
            return (
                summary.dynamic_uw + summary.leakage_uw,
                path,
                "signoff",
                StepEnum.POWER_ANALYSIS.value,
            )

    if flow_states.get(StepEnum.SYNTHESIS.value) == StateEnum.Success.value:
        path = (
            directories.path(StepEnum.SYNTHESIS.value)
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


def _egr_overflow_grid(directories: StepDirectories, flow_states: dict):
    """Read (total GCells, overflowed GCells, path) from the placement EGR map.

    ``placement.map.json`` (or legacy ``place.map.json``) records the union
    overflow CSV, one cell per GCell, so the grid size and overflowed-GCell
    fraction are derivable from it. Returns ``(None, None, None)`` when absent
    or invalid.
    """
    empty = (None, None, None)
    if flow_states.get(StepEnum.PLACEMENT.value) != StateEnum.Success.value:
        return empty
    feature_dir = directories.path(StepEnum.PLACEMENT.value) / "feature"
    map_data = json_read(feature_dir / "placement.map.json")
    if not map_data:
        map_data = json_read(feature_dir / "place.map.json")
    recorded = (
        JsonObject(map_data).get_obj("Congestion").get_obj("map").get_obj("egr").get_str("union")
    )
    if not recorded:
        return empty
    # Prefer the copy beside the map file: recorded paths may be absolute and
    # stop resolving once a workspace is moved.
    candidates = [feature_dir / "egr_congestion_map" / Path(recorded).name, Path(recorded)]
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        return empty
    total = overflowed = 0
    try:
        with path.open(newline="", encoding="utf-8") as file:
            for row in csv_reader(file):
                for cell in row:
                    value = float(cell)
                    if not isfinite(value) or value < 0:
                        return empty
                    total += 1
                    overflowed += value > 0
    except (OSError, UnicodeDecodeError, ValueError):
        return empty
    if total == 0:
        return empty
    return total, overflowed, str(path)


def _resolve_parameters(parameters: dict, warnings: list) -> tuple:
    """Resolve (tclk_ns, profile, power_budget_uw) from flat parameters."""
    tclk_ns = None
    frequency_max = parameters.get("frequency_max")
    if frequency_max is not None:
        freq = finite_number(frequency_max)
        if freq is not None and freq > 0:
            tclk_ns = 1000.0 / float(freq)
        elif isinstance(frequency_max, (int, float)) and not isinstance(frequency_max, bool):
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
        finite_budget = finite_number(budget)
        if finite_budget is not None and finite_budget > 0:
            power_budget_uw = float(finite_budget) * 1e6
        else:
            warnings.append("qor_power_budget_w must be a positive number; power quality UNKNOWN")
    return tclk_ns, profile, power_budget_uw


def load_workspace_qor_inputs(workspace) -> QorInputs:
    workspace_root = Path(workspace.directory)
    design = getattr(getattr(workspace, "design", None), "name", "") or getattr(
        workspace, "name", ""
    )
    if not design:
        parameters = _parameters(workspace, workspace_root)
        design = parameters.get("design") or parameters.get("Design") or ""

    warnings: list = []
    parameters = _parameters(workspace, workspace_root)
    tclk_ns, profile, power_budget_uw = _resolve_parameters(parameters, warnings)
    records = _flow_records(workspace, workspace_root)
    flow_states = _flow_states(records)
    directories = StepDirectories.from_records(workspace_root, records)

    step_payloads: list = []
    analyzed_steps: list = []
    parse_failures = 0
    invalid_selector_count = 0
    for step_value in SCORED_STEP_VALUES:
        if flow_states.get(step_value) != StateEnum.Success.value:
            continue
        step_dir = directories.path(step_value)
        cache = step_dir / "analysis" / "qor_metrics.json"
        payload = json_read(cache)
        records = _payload_metrics(payload)
        if payload is None or not records:
            parse_failures += 1
            continue
        records = _drop_unverified_gate_metrics(step_dir, cache, records, warnings)
        analyzed_steps.append(step_value)
        integrity = payload.get("integrity")
        if isinstance(integrity, dict):
            invalid_selector_count += len(integrity.get("invalid_metric_source_ids") or [])
            invalid_selector_count += len(integrity.get("invalid_detail_ids") or [])
        step_payloads.append((step_value, records))

    metrics = _select_metrics(step_payloads, warnings)

    def _metric_value(metric_id: str) -> float | None:
        record = metrics.get(metric_id)
        return record.value if record is not None else None

    power_total_uw, power_source, power_source_kind, power_corner = _power_summary(
        workspace, directories, flow_states
    )
    corners, sta_setup_only, sta_corner_parse_failures = _corner_slack(
        workspace, directories, flow_states
    )
    egr_gcells, egr_overflowed, egr_source = _egr_overflow_grid(directories, flow_states)

    return QorInputs(
        design=design,
        workspace_path=str(workspace_root),
        flow_states=flow_states,
        metrics=metrics,
        analyzed_steps=analyzed_steps,
        parse_failures=parse_failures,
        invalid_selector_count=invalid_selector_count,
        corners=corners,
        sta_corner_parse_failures=sta_corner_parse_failures,
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
        egr_gcell_count=egr_gcells,
        egr_overflowed_gcell_count=egr_overflowed,
        egr_grid_source_path=egr_source,
    )
