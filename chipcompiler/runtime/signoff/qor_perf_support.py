"""Read numeric QoR gate metrics from on-disk summaries for performance checks.

Pure helpers over schema-v4 ``qor_summary`` payloads. Catalog ``performance.*``
slots stay unbound; this module does not write checklist predicates.
"""

from __future__ import annotations

import json
import operator
from pathlib import Path
from typing import Any, Callable

_OPS: dict[str, Callable[[float, float], bool]] = {
    "==": operator.eq,
    "!=": operator.ne,
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
}


def load_qor_summary(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("qor_summary root must be an object")
    return payload


def analysis_qor_summary_path(workspace: str | Path, step_directory: str) -> Path:
    """Conventional ``<workspace>/<step>/analysis/qor_summary.json`` location."""
    return Path(workspace) / step_directory / "analysis" / "qor_summary.json"


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number:  # NaN
        return None
    return number


def _gate_metric_entries(summary: dict[str, Any]) -> list[tuple[str, float]]:
    gates = summary.get("gates")
    if not isinstance(gates, list):
        return []
    entries: list[tuple[str, float]] = []
    for gate in gates:
        if not isinstance(gate, dict):
            continue
        metrics = gate.get("metrics")
        if not isinstance(metrics, list):
            continue
        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            metric_id = metric.get("id")
            if not isinstance(metric_id, str) or not metric_id:
                continue
            actual = _finite_number(metric.get("actual"))
            if actual is None:
                continue
            entries.append((metric_id, actual))
    return entries


def metric_values_from_summary(summary: dict[str, Any]) -> dict[str, float]:
    """Last finite ``actual`` wins when a metric id repeats across gates."""
    return dict(_gate_metric_entries(summary))


def load_metric_values(path: str | Path) -> dict[str, float]:
    return metric_values_from_summary(load_qor_summary(path))


def require_metric(summary: dict[str, Any], metric_id: str) -> float:
    values = metric_values_from_summary(summary)
    if metric_id not in values:
        raise KeyError(f"metric {metric_id!r} missing from qor_summary gates")
    return values[metric_id]


def metric_satisfies(actual: float, op: str, expected: float) -> bool:
    compare = _OPS.get(op)
    if compare is None:
        raise ValueError(f"unsupported metric operator {op!r}")
    return bool(compare(actual, expected))


def check_metric(
    summary: dict[str, Any],
    metric_id: str,
    op: str,
    expected: float,
) -> bool:
    return metric_satisfies(require_metric(summary, metric_id), op, expected)
