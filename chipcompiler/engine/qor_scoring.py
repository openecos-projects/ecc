from dataclasses import dataclass
from typing import Any

QOR_SCORE_THRESHOLD = 60

DIMENSION_WEIGHTS = {
    "timing": 0.35,
    "power_integrity": 0.25,
    "routability_physical": 0.2,
    "area_cost": 0.1,
    "clock_robustness_dfm": 0.1,
    "runtime": 0.0,
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

_SLACK_METRICS = {"sta_setup_wns", "sta_setup_tns", "sta_hold_wns", "sta_hold_tns"}
_ROLE_PRIORITY = {"final": 0, "gate": 1, "trend": 2, "none": 3}


@dataclass(frozen=True)
class QorScoringMetric:
    step: str
    metric_id: str
    value: float
    dimension: str
    direction: str
    scope: str
    corner: str | None
    project_role: str
    rating_score: bool
    payload: Any = None


@dataclass(frozen=True)
class ScoredQorMetric:
    metric: QorScoringMetric
    score: float | None


@dataclass(frozen=True)
class QorScoringResult:
    area_scoring_step: str | None
    metrics: tuple[ScoredQorMetric, ...]
    dimensions: dict[str, tuple[float, int]]
    overall_score: float | None


def score_qor(records: list[QorScoringMetric]) -> QorScoringResult:
    area_step = next(
        (
            record.step
            for record in reversed(records)
            if record.dimension == "area_cost" and record.rating_score
        ),
        None,
    )
    selected: dict[tuple[str, str, str], tuple[int, int, QorScoringMetric]] = {}
    for order, record in enumerate(records):
        if record.project_role == "none":
            continue
        if record.dimension == "area_cost" and record.step != area_step:
            continue
        key = (record.metric_id, record.scope, record.corner or "")
        candidate = (_ROLE_PRIORITY.get(record.project_role, 3), -order, record)
        if key not in selected or candidate[:2] < selected[key][:2]:
            selected[key] = candidate

    scored = tuple(
        ScoredQorMetric(record, score_metric(record) if record.rating_score else None)
        for _role, _order, record in sorted(selected.values(), key=lambda item: item[2].metric_id)
    )
    by_dimension: dict[str, list[float]] = {}
    for item in scored:
        if item.score is not None:
            by_dimension.setdefault(item.metric.dimension, []).append(item.score)
    dimensions = {
        dimension: (
            round(sum(by_dimension[dimension]) / len(by_dimension[dimension]), 1),
            len(by_dimension[dimension]),
        )
        for dimension in DIMENSION_WEIGHTS
        if dimension in by_dimension
    }
    weighted = sum(
        score * DIMENSION_WEIGHTS[dimension]
        for dimension, (score, _count) in dimensions.items()
        if DIMENSION_WEIGHTS[dimension] > 0
    )
    overall = (
        round(weighted, 1)
        if any(DIMENSION_WEIGHTS[dimension] > 0 for dimension in dimensions)
        else None
    )
    return QorScoringResult(area_step, scored, dimensions, overall)


def score_metric(record: QorScoringMetric) -> float | None:
    if record.direction == "trend_only":
        return None
    fail = METRIC_FAIL_VALUES.get(record.metric_id)
    if fail is None:
        return None
    if record.metric_id in _SLACK_METRICS:
        if fail >= 0:
            return None
        return 100.0 if record.value >= 0 else _clamp(100 * (record.value - fail) / -fail)
    if record.direction == "target_range":
        if record.metric_id != "core_utilization":
            return None
        if 0.45 <= record.value <= 0.7:
            return 100.0
        if record.value < 0.45:
            return _clamp(100 * record.value / 0.45)
        return _clamp(100 * (fail - record.value) / (fail - 0.7))
    if fail <= 0:
        return None
    if record.direction == "lower_is_better":
        return _clamp(100 * (fail - record.value) / fail)
    if record.direction == "higher_is_better":
        return _clamp(100 * record.value / fail)
    return None


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))
