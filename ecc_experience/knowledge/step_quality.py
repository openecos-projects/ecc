"""Grade step evidence without collapsing missing facts into a numeric score."""

from typing import Any

from ecc_experience.files import digest
from ecc_experience.models import parameter_evidence_level

QUALITY_SCHEMA = "ecc-experience-step-quality/1"
LEVELS = ("high", "medium", "low", "unknown")


def grade_case(
    case: Any,
    verification: Any,
    features: dict[str, Any],
    *,
    stability: str = "single_observation",
) -> dict[str, Any]:
    steps = features.get("steps")
    if not isinstance(steps, list):
        steps = []
    parameter_level = parameter_evidence_level(case)
    rows = [
        _grade_step(
            step,
            verification=verification,
            parameter_level=parameter_level,
            failure=case.failure is not None,
        )
        for step in steps
        if isinstance(step, dict)
    ]
    overall = _overall(verification, rows, stability)
    identity = {
        "case_id": case.case_id,
        "steps": rows,
        "stability": stability,
        "level": overall,
    }
    return {
        "schema": QUALITY_SCHEMA,
        "case_id": case.case_id,
        "level": overall,
        "stability": stability,
        "steps": rows,
        "quality_generation": f"quality-{digest(identity)}",
        "limitations": [
            "A single successful observation cannot establish repeat stability",
            "Shared process-tree resource measurements remain partial evidence",
            "Configured parameters do not prove tool consumption",
        ],
    }


def quality_rank(level: str) -> int:
    return {"unknown": 0, "low": 1, "medium": 2, "high": 3}.get(level, 0)


def _grade_step(
    step: dict[str, Any],
    *,
    verification: Any,
    parameter_level: str,
    failure: bool,
) -> dict[str, Any]:
    metrics = step.get("metrics")
    if not isinstance(metrics, list):
        metrics = []
    metric_statuses = []
    for item in metrics:
        if isinstance(item, dict) and isinstance(item.get("status"), str):
            metric_statuses.append(item["status"])
    resource = step.get("resource_observation")
    measurement = resource.get("measurement") if isinstance(resource, dict) else None
    checks = [
        _check(
            "execution",
            "pass" if step.get("state") == "Success" else "fail",
            f"step state={step.get('state')}",
        ),
        _check(
            "report_schema",
            "pass" if isinstance(step.get("analysis_revision"), str) and metrics else "unknown",
            "analysis revision and metrics are both required",
        ),
        _check(
            "metric_completeness",
            "pass"
            if metrics and all(status == "available" for status in metric_statuses)
            else "unknown",
            f"available={metric_statuses.count('available')}/{len(metric_statuses)}",
        ),
        _check(
            "scope_and_corner",
            "pass"
            if metrics
            and all(
                isinstance(item.get("scope"), str) and isinstance(item.get("corner"), str)
                for item in metrics
                if isinstance(item, dict)
            )
            else "unknown",
            "metric scope and corner must be explicit",
        ),
        _check(
            "parameter_materialization",
            "pass" if parameter_level in {"applied", "materialized"} else "unknown",
            f"parameter evidence={parameter_level}",
        ),
        _check(
            "resource_measurement",
            "pass"
            if isinstance(measurement, dict)
            and measurement.get("status") == "available"
            and measurement.get("scope") != "shared_process_tree"
            else "unknown",
            "resource measurement scope must be available and isolated",
        ),
        _check(
            "failure_taxonomy",
            "pass" if failure else "unknown",
            "failure taxonomy binding is missing",
        ),
        _check(
            "verification",
            "pass"
            if verification.status == "pass" and verification.integrity == "pass"
            else "fail"
            if verification.status == "fail" or verification.integrity == "fail"
            else "unknown",
            f"verification={verification.status}/{verification.integrity}",
        ),
    ]
    return {
        "step": step.get("step"),
        "level": _level(checks),
        "checks": checks,
    }


def _overall(verification: Any, rows: list[dict[str, Any]], stability: str) -> str:
    if verification.status == "fail" or verification.integrity == "fail":
        return "low"
    if not rows:
        return "unknown"
    if any(row["level"] == "low" for row in rows):
        return "low"
    if all(row["level"] == "high" for row in rows) and stability == "consistent":
        return "high"
    if any(row["level"] in {"medium", "high"} for row in rows):
        return "medium"
    return "unknown"


def _level(checks: list[dict[str, str]]) -> str:
    statuses = {item["status"] for item in checks}
    if "fail" in statuses:
        return "low"
    if statuses == {"pass"}:
        return "high"
    if "pass" in statuses:
        return "medium"
    return "unknown"


def _check(check_id: str, status: str, detail: str) -> dict[str, str]:
    return {"id": check_id, "status": status, "detail": detail}
