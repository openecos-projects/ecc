import math
from typing import Any

from .qor_scoring import (
    DIMENSION_WEIGHTS,
    QOR_SCORE_THRESHOLD,
    QorScoringMetric,
    score_qor,
)


def build_workspace_qor_assessment(analysis: dict[str, Any]) -> dict[str, Any]:
    metrics = []
    step_summaries = []
    metric_steps = []
    for step in analysis["steps"]:
        if step["flowState"] != "Success":
            continue
        step_id = step["stepId"]
        metrics_file = step["metrics"]
        payload = metrics_file["data"] if metrics_file["status"] == "available" else {}
        records = payload.get("metrics")
        valid_records = [record for record in records or [] if _valid_metric(record)]
        metrics.extend(valid_records)
        metric_steps.extend((step_id, record) for record in valid_records)
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

    if not metrics:
        return {
            "status": "unavailable",
            "score": {"value": None, "threshold": QOR_SCORE_THRESHOLD, "gate": "unavailable"},
            "areaScoringStep": None,
            "dimensionScores": {},
            "metrics": [],
            "steps": step_summaries,
        }

    gate = _gate_status(step_summaries)
    scoring = score_qor(
        [
            QorScoringMetric(
                step=step_id,
                metric_id=record["id"],
                value=float(record["value"]),
                dimension=record["category"],
                direction=record["direction"],
                scope=record["scope"],
                corner=record.get("corner"),
                project_role=record["project_role"],
                rating_score=record["rating"]["score"],
            )
            for step_id, record in metric_steps
        ]
    )
    return {
        "status": "ready",
        "score": {
            "value": scoring.overall_score,
            "threshold": QOR_SCORE_THRESHOLD,
            "gate": gate,
        },
        "areaScoringStep": scoring.area_scoring_step,
        "dimensionScores": {
            dimension: score for dimension, (score, _count) in scoring.dimensions.items()
        },
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
        and record.get("category") in DIMENSION_WEIGHTS
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


def _gate_status(steps: list[dict[str, Any]]) -> str:
    statuses = {step["status"] for step in steps}
    if "blocked" in statuses:
        return "blocked"
    if statuses & {"incomplete", "unavailable"}:
        return "incomplete"
    return "pass"
