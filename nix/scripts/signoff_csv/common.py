"""Pure filesystem/JSON helpers for the standalone signoff CSV collector."""

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


STEP_DIRECTORIES = {
    "Synthesis": "Synthesis_yosys",
    "postFloorplan": "postFloorplan_ecc",
    "place": "place_dreamplace",
    "drc": "drc_ecc",
    "lvs": "lvs_ecc",
    "sta": "sta_ecc",
    "Harden": "Harden_ecc",
}

LEC_DIRECTORIES = {
    "kepler_formal": "postRouteLec_kepler_formal",
    "yosys_lec": "postRouteLec_yosys_lec",
    "lec_dual": "postRouteLec_dual",
}


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def relative_to_workspace(workspace: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def flow_ledger(workspace: Path) -> dict[str, Any]:
    data = read_json(workspace / "home" / "flow.json")
    if not isinstance(data, dict):
        return {"design": workspace.name, "steps": []}
    return {
        "design": str(data.get("design") or workspace.name),
        "steps": data.get("steps") if isinstance(data.get("steps"), list) else [],
    }


def step_tool(flow: dict[str, Any], step_name: str) -> str:
    for step in flow.get("steps", []):
        if isinstance(step, dict) and step.get("name") == step_name:
            return str(step.get("tool", ""))
    return ""


def step_directory(flow: dict[str, Any], step_name: str) -> str:
    if step_name == "postRouteLec":
        tool = step_tool(flow, step_name).casefold()
        return LEC_DIRECTORIES.get(tool, "postRouteLec_kepler_formal")
    return STEP_DIRECTORIES.get(step_name, f"{step_name}_ecc")


def metric_records(workspace: Path, directory: str) -> dict[str, dict[str, Any]]:
    path = workspace / directory / "analysis" / "qor_metrics.json"
    data = read_json(path)
    if not isinstance(data, dict) or data.get("schema_version") != 3:
        return {}
    metrics = data.get("metrics")
    if not isinstance(metrics, list):
        return {}
    return {
        str(record.get("id")): record
        for record in metrics
        if isinstance(record, dict) and isinstance(record.get("id"), str)
    }


def metric_number(record: dict[str, Any] | None) -> str:
    if not isinstance(record, dict):
        return ""
    value = record.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    return str(value)


def gate_state(workspace: Path, directory: str, gate_id: str) -> str:
    path = workspace / directory / "analysis" / "qor_summary.json"
    data = read_json(path)
    if not isinstance(data, dict):
        return "unavailable"
    gates = data.get("gates")
    if not isinstance(gates, list):
        return "unavailable"
    for gate in gates:
        if isinstance(gate, dict) and gate.get("id") == gate_id:
            state = gate.get("state")
            return str(state) if isinstance(state, str) else "unavailable"
    return "unavailable"


def artifact_row(workspace: Path, path: Path, metric: str) -> dict[str, Any]:
    present = path.is_file()
    return {
        "kind": "artifact",
        "metric": metric,
        "value": "",
        "unit": "",
        "source": relative_to_workspace(workspace, path),
        "present": str(present).lower(),
        "sha256": sha256_file(path) if present else "",
        "bytes": str(path.stat().st_size) if present else "",
    }
