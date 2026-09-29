"""Validated QoR metric records collected into the Snapshot `metrics` projection.

The collection is pure data filtering: metric records from per-step
``analysis/qor_metrics.json`` files are canonicalized and validated. QoR
scoring lives in the qor-v3 engine (`chipcompiler.analysis.qor`) and reaches
the Snapshot through `qorSnapshotExtension`; this module keeps no scoring
rules of its own.
"""

import math
from typing import Any

_LEGACY_METRIC_CATEGORIES = {"power": "power_integrity"}
METRIC_CATEGORIES = frozenset(
    {
        "timing",
        "power_integrity",
        "routability_physical",
        "area_cost",
        "clock_robustness_dfm",
        "runtime",
    }
)


def collect_metric_records(payload: Any) -> list[dict[str, Any]]:
    """Validated metric records from one ``qor_metrics.json`` payload (schema 3)."""
    if not isinstance(payload, dict) or payload.get("schema_version") != 3:
        return []
    records = payload.get("metrics")
    if not isinstance(records, list):
        return []
    return [
        record
        for record in (_canonical_metric_category(record) for record in records)
        if _valid_metric(record)
    ]


def _canonical_metric_category(record: Any) -> Any:
    if not isinstance(record, dict):
        return record
    category = record.get("category")
    mapped = _LEGACY_METRIC_CATEGORIES.get(category, category)
    if mapped != category and mapped in METRIC_CATEGORIES:
        return {**record, "category": mapped}
    return record


def _valid_metric(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    value = record.get("value")
    rating = record.get("rating")
    corner = record.get("corner")
    corner_context = record.get("corner_context")
    return (
        isinstance(record.get("id"), str)
        and isinstance(record.get("display_name"), str)
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and record.get("category") in METRIC_CATEGORIES
        and record.get("direction")
        in {"higher_is_better", "lower_is_better", "target_range", "trend_only"}
        and isinstance(record.get("scope"), str)
        and (corner is None or isinstance(corner, str))
        and (corner_context is None or isinstance(corner_context, dict))
        and isinstance(record.get("analysis_group"), str)
        and isinstance(rating, dict)
        and isinstance(rating.get("gate"), bool)
        and isinstance(rating.get("score"), bool)
        and isinstance(rating.get("trend"), bool)
        and record.get("project_role") in {"final", "trend", "gate", "none"}
        and record.get("step_role") in {"primary", "secondary", "detail", "hidden"}
        and record.get("confidence") in {"high", "medium", "low"}
        and isinstance(record.get("source"), dict)
    )
