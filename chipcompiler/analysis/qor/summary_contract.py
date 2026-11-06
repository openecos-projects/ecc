"""Readers for the current per-step ``analysis/qor_summary.json`` contract.

Only schema 4 is supported. Older summaries are treated as unavailable.
"""

from typing import Any

QOR_SUMMARY_SCHEMA_VERSION = 4
_QUALITY_STATES = frozenset({"pass", "blocked", "incomplete", "unavailable"})


def summary_schema_version(summary: Any) -> int | None:
    if not isinstance(summary, dict):
        return None
    version = summary.get("schema_version")
    return version if isinstance(version, int) and not isinstance(version, bool) else None


def is_supported_summary(summary: Any) -> bool:
    return summary_schema_version(summary) == QOR_SUMMARY_SCHEMA_VERSION


def summary_analysis_revision(summary: Any) -> str | None:
    if not isinstance(summary, dict):
        return None
    revision = summary.get("analysis_revision")
    return revision if isinstance(revision, str) and revision else None


def summary_quality_status(summary: Any) -> str | None:
    """Return the current summary's quality verdict."""
    if not is_supported_summary(summary):
        return None
    status = summary.get("quality_status")
    return status if status in _QUALITY_STATES else None


def summary_gates(summary: Any) -> list[dict]:
    """Return the current summary's gate records."""
    if not is_supported_summary(summary):
        return []
    gates = summary.get("gates")
    return [gate for gate in gates if isinstance(gate, dict)] if isinstance(gates, list) else []


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
