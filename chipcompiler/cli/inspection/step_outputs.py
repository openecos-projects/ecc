from pathlib import Path

from chipcompiler.cli.core.output import normalize_step_name
from chipcompiler.cli.inspection.artifact_evidence import inspect_artifact
from chipcompiler.engine.snapshot import (
    EngineeringSnapshotError,
    read_engineering_snapshot_from_directory,
)


def output_records(workspace_dir: str, step_token: str, state: str) -> list[dict]:
    try:
        snapshot = read_engineering_snapshot_from_directory(workspace_dir)
    except (EngineeringSnapshotError, OSError, ValueError) as exc:
        return [
            {
                "step": step_token,
                "section": "outputs",
                "section_status": "unavailable",
                "reason": str(exc),
            }
        ]
    root = Path(workspace_dir).resolve()
    records = []
    if "stepOutputs" not in snapshot:
        return [
            {
                "step": step_token,
                "section": "outputs",
                "section_status": "unavailable",
                "reason": "snapshot has no step output index; no migration was performed",
            }
        ]
    invalidated = snapshot.get("stalePredecessor", {}).get("invalidatedStepIds", [])
    current = state == "success" and step_token not in {
        normalize_step_name(name) for name in invalidated
    }
    for step in snapshot["stepOutputs"]["steps"]:
        if normalize_step_name(step["step"]) != step_token:
            continue
        for role in ("verilog", "def"):
            artifact = step.get(role)
            if artifact is None:
                continue
            evidence = inspect_artifact(root, artifact["path"])
            record = {
                "step": step_token,
                "section": "outputs",
                "kind": "artifact",
                "role": role,
                **evidence,
                "validity": "unknown" if current else "not_current",
            }
            if evidence["availability"] != "outside_workspace":
                record["source"] = "home/engineering-snapshot.json"
            records.append(record)
    return records
