"""Assemble Snapshot `qorAssessment` from committed analysis.

The assessment is pure data collection: validated per-step metric
records and Success-step summaries. QoR scoring lives in the qor-v3
engine (`chipcompiler.analysis.qor`) and reaches the Snapshot through
`qorSnapshotExtension`; this module keeps no scoring rules of its own.
"""

import math
from typing import Any

from chipcompiler.engine.analysis import METRIC_CATEGORIES


def build_workspace_qor_assessment(analysis: dict[str, Any]) -> dict[str, Any]:
    metrics = []
    step_summaries = []
    for step in analysis["steps"]:
        if step["flowState"] != "Success":
            continue
        step_id = step["stepId"]
        metrics_file = step["metrics"]
        payload = metrics_file["data"] if metrics_file["status"] == "available" else {}
        records = payload.get("metrics")
        valid_records = [record for record in records or [] if _valid_metric(record)]
        metrics.extend(valid_records)
        summary_file = step["summary"]
        summary = summary_file["data"] if summary_file["status"] == "available" else {}
        summary_status = (
            str(summary.get("quality_status", "incomplete"))
            if summary.get("schema_version") == 4
            else "unavailable"
        )
        step_summaries.append(
            {
                "stepId": step_id,
                "order": step["order"],
                "name": step_id,
                "status": summary_status,
                "summaryMetricCount": len(valid_records),
            }
        )

    return {
        "status": "ready" if metrics else "unavailable",
        "metrics": metrics,
        "steps": step_summaries,
    }


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
