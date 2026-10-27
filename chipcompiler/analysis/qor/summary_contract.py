"""Compatibility helpers for the per-step ``analysis/qor_summary.json`` contract.

Schema 4 is the current producer contract. Schema 3 remains readable so
signoff packages can still diagnose workspaces produced before the v4 switch.
Only this module interprets the two wire shapes; callers consume normalized
gates and status fields.
"""

from typing import Any

QOR_SUMMARY_SCHEMA_VERSION = 4
QOR_SUMMARY_SUPPORTED_SCHEMA_VERSIONS = frozenset({3, 4})
_QUALITY_STATES = frozenset({"pass", "blocked", "incomplete", "unavailable"})


def summary_schema_version(summary: Any) -> int | None:
    if not isinstance(summary, dict):
        return None
    version = summary.get("schema_version")
    return version if isinstance(version, int) and not isinstance(version, bool) else None


def is_supported_summary(summary: Any) -> bool:
    return summary_schema_version(summary) in QOR_SUMMARY_SUPPORTED_SCHEMA_VERSIONS


def summary_analysis_revision(summary: Any) -> str | None:
    if not isinstance(summary, dict):
        return None
    revision = summary.get("analysis_revision")
    return revision if isinstance(revision, str) and revision else None


def summary_quality_status(summary: Any) -> str | None:
    """Return the normalized quality verdict for a v3 or v4 summary."""
    if not is_supported_summary(summary):
        return None
    if summary_schema_version(summary) == 4:
        status = summary.get("quality_status")
    else:
        status = summary.get("status")
    return status if status in _QUALITY_STATES else None


def summary_gates(summary: Any) -> list[dict]:
    """Return gate records normalized to the v4 shape."""
    if not is_supported_summary(summary):
        return []
    if summary_schema_version(summary) == 4:
        gates = summary.get("gates")
        return [gate for gate in gates if isinstance(gate, dict)] if isinstance(gates, list) else []

    gates = summary.get("hard_gates")
    if not isinstance(gates, list):
        return []
    normalized = []
    for raw in gates:
        if not isinstance(raw, dict):
            continue
        gate_id = raw.get("id")
        if not isinstance(gate_id, str) or not gate_id:
            continue
        passed = raw.get("passed") is True
        normalized.append(
            {
                "id": gate_id,
                "title": str(raw.get("title") or raw.get("metric") or gate_id),
                "state": "pass" if passed else "failed",
                "blocking": True,
                "metrics": [
                    {
                        "id": str(raw.get("metric") or gate_id),
                        "actual": raw.get("actual"),
                        "operator": str(raw.get("operator") or "=="),
                        "expected": raw.get("threshold"),
                    }
                ],
                "evidence": raw.get("evidence") if isinstance(raw.get("evidence"), list) else [],
            }
        )
    return normalized


def summary_blocking_issues(summary: Any) -> list[dict]:
    """Return v3 blocking issues; v4 failures are represented by failed gates."""
    if not is_supported_summary(summary) or summary_schema_version(summary) == 4:
        return []
    issues = summary.get("blocking_issues")
    return (
        [issue for issue in issues if isinstance(issue, dict)] if isinstance(issues, list) else []
    )


def summary_missing_metrics(summary: Any) -> list[dict]:
    if not is_supported_summary(summary):
        return []
    missing = summary.get("missing_metrics")
    return [item for item in missing if isinstance(item, dict)] if isinstance(missing, list) else []


def gate_reason(gate: dict) -> str:
    """Render a stable human-readable reason for one failed gate."""
    metrics = gate.get("metrics")
    parts = []
    for metric in metrics if isinstance(metrics, list) else []:
        if not isinstance(metric, dict) or metric.get("id") is None:
            continue
        metric_id = str(metric.get("id"))
        actual = metric.get("actual")
        operator = str(metric.get("operator") or "")
        expected = metric.get("expected")
        parts.append(f"{metric_id}={actual} (required {operator} {expected})")
    return "; ".join(parts) or str(gate.get("title") or "Current QoR analysis blocked signoff.")
