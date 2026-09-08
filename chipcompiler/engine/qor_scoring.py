from dataclasses import dataclass
from typing import Any

from .qor_report import (
    _STEP_ENUM_TO_LABEL,
    QorMetricRecord,
    _select_project_records,
    _weighted_overall,
    score_record,
)
from .qor_report import (
    DIMENSION_WEIGHTS as DIMENSION_WEIGHTS,
)
from .qor_report import (
    QOR_SCORE_THRESHOLD as QOR_SCORE_THRESHOLD,
)


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
    canonical_pairs = tuple((record, _canonical_record(record)) for record in records)
    canonical = tuple(item[1] for item in canonical_pairs)
    area_step = next(
        (
            record.step
            for record in reversed(canonical)
            if record.dimension == "area_cost" and record.rating_score
        ),
        None,
    )
    selected = _select_project_records(canonical, area_step)
    original_by_canonical_id = {
        id(canonical_record): original for original, canonical_record in canonical_pairs
    }
    scored = tuple(
        ScoredQorMetric(
            original_by_canonical_id.get(id(record), _restore_record(record)),
            score_record(record) if record.rating_score else None,
        )
        for record in selected
    )
    by_dimension: dict[str, list[float]] = {}
    for item in scored:
        if item.score is not None:
            by_dimension.setdefault(item.metric.dimension, []).append(item.score)
    dimensions = {
        dimension: (round(sum(values) / len(values), 1), len(values))
        for dimension, values in by_dimension.items()
    }
    return QorScoringResult(
        area_step,
        scored,
        dimensions,
        round(_weighted_overall({key: value[0] for key, value in dimensions.items()}), 1)
        if dimensions
        else None,
    )


def score_metric(record: QorScoringMetric) -> float | None:
    return score_record(_canonical_record(record))


def _canonical_record(record: QorScoringMetric) -> QorMetricRecord:
    return QorMetricRecord(
        step=_STEP_ENUM_TO_LABEL.get(record.step, record.step),
        metric_name=record.metric_id,
        display_name=record.metric_id,
        value=record.value,
        dimension=record.dimension,
        polarity=record.direction,
        scope=record.scope,
        corner=record.corner,
        project_role=record.project_role,
        step_role="detail",
        rating_score=record.rating_score,
    )


def _restore_record(record: QorMetricRecord) -> QorScoringMetric:
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
    )
