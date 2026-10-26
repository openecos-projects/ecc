"""Read numeric QoR gate metrics from on-disk summaries for performance checks.

Pure helpers over schema-v4 ``qor_summary`` payloads. Catalog ``performance.*``
slots stay unbound; this module does not write checklist predicates.

In:
    path / summary — on-disk or loaded qor_summary JSON
Out:
    metric id → finite actual; or bool from compare
Entry:
    check_metric()  chipcompiler/runtime/signoff/qor_perf_support.py
See:
    SIGNOFF_ITEM_CATALOG (performance.*)  chipcompiler/runtime/signoff/catalog.py
    signoff_baseline.py                   nix/scripts/signoff_baseline.py
"""

from __future__ import annotations

import json
import operator
from collections.abc import Callable
from pathlib import Path
from typing import Any

_OPS: dict[str, Callable[[float, float], bool]] = {
    "==": operator.eq,
    "!=": operator.ne,
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
}


def load_qor_summary(path: str | Path) -> dict[str, Any]:
    """Load a qor_summary JSON object from disk.

    In:
        path — filesystem path to qor_summary.json
    Out:
        dict — root object
    See:
        load_metric_values()  chipcompiler/runtime/signoff/qor_perf_support.py
        check_metric()        chipcompiler/runtime/signoff/qor_perf_support.py
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("qor_summary root must be an object")
    return payload


def analysis_qor_summary_path(workspace: str | Path, step_directory: str) -> Path:
    """Conventional ``<workspace>/<step>/analysis/qor_summary.json`` location.

    In:
        workspace — workspace root
        step_directory — step dir name (e.g. drc_ecc, sta_ecc)
    Out:
        Path — expected summary path (may not exist yet)
    See:
        load_qor_summary()  chipcompiler/runtime/signoff/qor_perf_support.py
    """
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
    """Project gate metrics to id→actual (last finite wins).

    In:
        summary — loaded qor_summary object
    Out:
        dict[str, float] — metric_id → actual
    See:
        require_metric()  chipcompiler/runtime/signoff/qor_perf_support.py
        check_metric()    chipcompiler/runtime/signoff/qor_perf_support.py
    """
    return dict(_gate_metric_entries(summary))


def load_metric_values(path: str | Path) -> dict[str, float]:
    """Load summary from disk then project metrics.

    In:
        path — qor_summary.json path
    Out:
        dict[str, float] — metric_id → actual
    See:
        load_qor_summary()            chipcompiler/runtime/signoff/qor_perf_support.py
        metric_values_from_summary()  chipcompiler/runtime/signoff/qor_perf_support.py
    """
    return metric_values_from_summary(load_qor_summary(path))


def require_metric(summary: dict[str, Any], metric_id: str) -> float:
    """Fetch one metric actual or raise KeyError.

    In:
        summary — loaded qor_summary
        metric_id — e.g. drc_count, sta_setup_wns
    Out:
        float — finite actual
    See:
        metric_satisfies()  chipcompiler/runtime/signoff/qor_perf_support.py
        check_metric()      chipcompiler/runtime/signoff/qor_perf_support.py
    """
    values = metric_values_from_summary(summary)
    if metric_id not in values:
        raise KeyError(f"metric {metric_id!r} missing from qor_summary gates")
    return values[metric_id]


def metric_satisfies(actual: float, op: str, expected: float) -> bool:
    """Compare one actual against expected with a gate op.

    In:
        actual / expected — finite floats
        op — one of == != >= <= > <
    Out:
        bool — comparison result
    See:
        check_metric()  chipcompiler/runtime/signoff/qor_perf_support.py
    """
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
    """Require metric then compare (perf / baseline helper).

    In:
        summary — loaded qor_summary
        metric_id / op / expected — gate triple
    Out:
        bool — whether actual satisfies op expected
    Entry:
        (callers) test/engine/test_qor_perf_support.py
        signoff_baseline.py  nix/scripts/signoff_baseline.py
    See:
        require_metric()    chipcompiler/runtime/signoff/qor_perf_support.py
        metric_satisfies()  chipcompiler/runtime/signoff/qor_perf_support.py
    """
    return metric_satisfies(require_metric(summary, metric_id), op, expected)
