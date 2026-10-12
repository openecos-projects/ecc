from pathlib import Path

from chipcompiler.cli.core.output import normalize_step_name
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
            path = Path(artifact["path"])
            try:
                candidate = (root / path).resolve()
            except (OSError, RuntimeError) as exc:
                records.append(
                    {
                        "step": step_token,
                        "section": "outputs",
                        "kind": "artifact",
                        "role": role,
                        "path": artifact["path"],
                        "availability": "unreadable",
                        "validity": "unknown",
                        "reason": str(exc),
                    }
                )
                continue
            if not candidate.is_relative_to(root):
                records.append(
                    {
                        "step": step_token,
                        "section": "outputs",
                        "kind": "artifact",
                        "role": role,
                        "path": artifact["path"],
                        "availability": "outside_workspace",
                        "validity": "unknown",
                    }
                )
                continue
            try:
                exists = candidate.is_file()
                size = candidate.stat().st_size if exists else None
                availability = "available" if exists else "missing"
            except OSError:
                exists, size, availability = None, None, "unreadable"
            records.append(
                {
                    "step": step_token,
                    "section": "outputs",
                    "kind": "artifact",
                    "role": role,
                    "path": artifact["path"],
                    "exists": exists,
                    "bytes": size,
                    "availability": availability,
                    "validity": "unknown" if current else "not_current",
                    "source": "home/engineering-snapshot.json",
                }
            )
    return records
