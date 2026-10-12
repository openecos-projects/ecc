from math import isfinite
from pathlib import Path

from chipcompiler.analysis.qor.metric_registry import METRIC_REGISTRY
from chipcompiler.cli.core.output import normalize_state
from chipcompiler.cli.inspection.project_artifacts import read_workspace_artifact
from chipcompiler.data.step import STEP_DIRECTORIES, step_directory_for_tool
from chipcompiler.engine.snapshot_limits import CHECKLIST_READ_MAX_BYTES

_VIOLATION_METRICS = {
    "drc": ("drc_count",),
    "lvs": ("lvs_count",),
    "sta": ("sta_setup_violation_count", "sta_hold_violation_count"),
}


def checker_evidence(root: Path, step: dict, design: str) -> dict:
    record = {
        "availability": "not_verified",
        "verdict": "unknown",
        "has_violations": None,
        "violation_count": None,
        "counts": {},
        "source": None,
    }
    if normalize_state(step["state"]) != "success":
        return record
    name, tool = step["name"], step["tool"]
    directory = step_directory_for_tool(name, tool)
    if (
        name in STEP_DIRECTORIES
        and name not in {"lec", "postRouteLec"}
        and not directory.endswith(f"_{tool}")
    ):
        record["availability"] = "unsupported_tool"
        return record
    step_root = root / directory
    metric_ids = _VIOLATION_METRICS.get(name)
    if metric_ids is None:
        if name in {"lec", "postRouteLec"}:
            return _lec_evidence(root, step_root, name, design, record)
        record["availability"] = "not_applicable"
        return record
    path = step_root / "analysis" / "qor_metrics.json"
    record["source"] = str(path)
    result = read_workspace_artifact(root, path, CHECKLIST_READ_MAX_BYTES)
    record["availability"] = result.status
    if result.status != "available":
        return record
    payload = result.data
    if (
        payload.get("schema_version") != 3
        or payload.get("step") != name
        or payload.get("tool") != tool
        or payload.get("status") != "success"
        or not isinstance(payload.get("metrics"), list)
    ):
        record["availability"] = "invalid"
        return record
    integrity = payload.get("integrity", {})
    if not isinstance(integrity, dict) or not isinstance(
        integrity.get("invalid_metric_source_ids", []), list
    ):
        record["availability"] = "invalid"
        return record
    counts = {}
    for metric_id in metric_ids:
        if metric_id in integrity.get("invalid_metric_source_ids", []):
            record["availability"] = "invalid"
            return record
        candidates = [
            metric
            for metric in payload["metrics"]
            if isinstance(metric, dict) and metric.get("id") == metric_id
        ]
        if len(candidates) != 1:
            continue
        metric = candidates[0]
        if metric.get("unit") != METRIC_REGISTRY[metric_id][0]:
            record["availability"] = "invalid"
            return record
        value = metric.get("value")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or (isinstance(value, float) and not isfinite(value))
            or value < 0
            or int(value) != value
        ):
            record["availability"] = "invalid"
            return record
        counts[metric_id] = int(value)
    record["counts"] = counts
    if not counts:
        record["availability"] = "missing_count"
        return record
    complete = len(counts) == len(metric_ids)
    violated = any(count > 0 for count in counts.values())
    record["availability"] = "available" if complete else "partial"
    record["has_violations"] = True if violated else False if complete else None
    record["verdict"] = "violated" if violated else "clean" if complete else "unknown"
    if len(metric_ids) == 1:
        record["violation_count"] = counts[metric_ids[0]]
    return record


def _lec_evidence(root: Path, step_root: Path, name: str, design: str, record: dict) -> dict:
    path = step_root / "output" / f"{design}_{name}_result.json"
    record["source"] = str(path)
    result = read_workspace_artifact(root, path, CHECKLIST_READ_MAX_BYTES)
    record["availability"] = result.status
    if result.status != "available":
        return record
    if result.data.get("status") == "proven":
        record["verdict"] = "proven_saved"
    else:
        record["availability"] = "not_verified"
    return record
