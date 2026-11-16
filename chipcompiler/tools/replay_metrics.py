"""Compare only explicit physical-input metrics under compatible measurement conditions."""

import hashlib
import json
from pathlib import Path

STRUCTURAL = {
    "clock_area",
    "clock_count",
    "core_area",
    "core_utilization",
    "die_area",
    "instance_area",
    "instance_count",
    "macro_area",
    "macro_count",
    "stdcell_area",
    "stdcell_count",
    "filler_area",
    "filler_count",
}


def capture_baseline(step) -> dict | None:
    """A predecessor is resolved through the actual DEF, never timeline adjacency."""
    source = getattr(getattr(step, "input", None), "def_", None)
    if not source:
        return None
    source = Path(source).resolve()
    if not source.is_file() or source.parent.name != "output":
        return None
    owner = source.parent.parent
    metrics = owner / "analysis/qor_metrics.json"
    if not metrics.is_file() or metrics.stat().st_mtime_ns < source.stat().st_mtime_ns:
        return None
    with source.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "source_step": owner.name,
        "input_path": str(source),
        "input_sha256": digest,
        "metrics": json.loads(metrics.read_text()).get("metrics", []),
    }


def attach_comparisons(metrics: list, baseline: dict | None) -> list:
    if baseline is None:
        return metrics
    previous = {record.get("id"): record for record in baseline["metrics"]}
    result = []
    for metric in metrics:
        item = dict(metric)
        old = previous.get(item.get("id"))
        if old is not None and comparable(old, item):
            item["comparison"] = {
                "baseline_value": old["value"],
                "delta": item["value"] - old["value"],
                "source_step": baseline["source_step"],
                "basis_sha256": baseline["input_sha256"],
                "baseline_source": old.get("source"),
            }
        result.append(item)
    return result


def comparable(old: dict, new: dict) -> bool:
    if any(type(item.get("value")) not in (int, float) for item in (old, new)):
        return False
    if old.get("unit") != new.get("unit") or not new.get("unit"):
        return False
    if new.get("id") in STRUCTURAL:
        selectors = [item.get("source", {}).get("selector") for item in (old, new)]
        return bool(selectors[0]) and selectors[0] == selectors[1]
    # Legacy timing/power records lack sufficient context: omit their delta.
    context = new.get("comparison_context")
    required = {"corner", "check_type", "constraints", "libraries", "rc_model", "coverage"}
    return (
        isinstance(context, dict)
        and required <= context.keys()
        and all(context[key] is not None for key in required)
        and context == old.get("comparison_context")
    )
