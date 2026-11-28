"""Shared per-payload duplicate resolution for schema-v3 ``analysis/qor_metrics.json``.

Both the checklist reader (``chipcompiler.tools.ecc.qor_metrics.QorMetrics``)
and the workspace QoR loader (``chipcompiler.analysis.qor.loader``) consume the
same per-step ``qor_metrics.json`` metric array. Identical duplicates for a
metric id are harmless; any two records for the same metric id whose values
disagree (including boolean vs numeric such as ``False`` vs ``0``) mark that
metric id as conflicted.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

QOR_METRICS_SCHEMA_VERSION = 3


def metric_values_conflict(first: object, second: object) -> bool:
    """Whether two recorded metric values for the same id disagree."""
    if isinstance(first, bool) != isinstance(second, bool):
        return True
    return bool(first != second)


@dataclass(frozen=True)
class MetricRecordIndex:
    """Per-payload metric records indexed by id alongside value conflicts."""

    records: dict[str, dict[Any, Any]] = field(default_factory=dict)
    conflicts: dict[str, tuple[object, object]] = field(default_factory=dict)
    error: str | None = None


def index_metric_records(metrics: Sequence[object]) -> MetricRecordIndex:
    """Index per-step metric records by id and capture first conflicting value pair."""
    records: dict[str, dict[Any, Any]] = {}
    conflicts: dict[str, tuple[object, object]] = {}
    error: str | None = None
    for entry in metrics:
        if not isinstance(entry, dict):
            error = error or "qor_metrics.json contains a metric without a valid id"
            continue
        metric_id = entry.get("id")
        if not isinstance(metric_id, str) or not metric_id:
            error = error or "qor_metrics.json contains a metric without a valid id"
            continue
        existing = records.get(metric_id)
        if existing is None:
            records[metric_id] = entry
        elif metric_id not in conflicts and metric_values_conflict(
            existing.get("value"), entry.get("value")
        ):
            conflicts[metric_id] = (existing.get("value"), entry.get("value"))
    return MetricRecordIndex(records=records, conflicts=conflicts, error=error)
