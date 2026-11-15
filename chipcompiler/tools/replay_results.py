"""Freeze completion-only artifacts belonging to the current capture attempt."""

import json
import shutil
from pathlib import Path


def collect_results(step, directory: Path, started_unix_ns: int) -> dict:
    result: dict[str, object] = {"result_metrics": []}
    metrics = getattr(getattr(step, "analysis", None), "qor_metrics", None)
    if metrics and metrics.is_file() and metrics.stat().st_mtime_ns >= started_unix_ns:
        # Execution resource facts are finalized outside the tool invocation.
        # A freshly rewritten QoR file can still contain last run's resource
        # entries. Replay duration comes from its own monotonic capture clock.
        result["result_metrics"] = [
            metric
            for metric in json.loads(metrics.read_text()).get("metrics", [])
            if metric.get("category") != "runtime"
        ]
    feature = getattr(getattr(step, "feature", None), "dir", None)
    if step.name != "place" or not feature:
        return result
    # Existing map CSVs carry a layout.csv with explicit DBU rectangles. Never
    # infer grid coordinates from the image size or reuse stale maps on rerun.
    relative = "subflows/run-placement/overlays/maps"
    copied = False
    for category in sorted(Path(feature).glob("*_map")):
        layout = category / "layout.csv"
        if not layout.is_file() or layout.stat().st_mtime_ns < started_unix_ns:
            continue
        for path in category.glob("*.csv"):
            if path.is_file() and path.stat().st_mtime_ns >= started_unix_ns:
                target = directory / relative / category.name / path.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                copied = True
    if copied:
        result["maps"] = relative
    return result
