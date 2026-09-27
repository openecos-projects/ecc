"""Transport-neutral recovery for interrupted Workspace flow steps."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from chipcompiler.data import StateEnum
from chipcompiler.utility import json_read, json_write


def recover_interrupted_run(
    workspace_dir: str | Path,
    *,
    run_id: str | None,
    allow_markerless: bool,
) -> tuple[str, ...]:
    """Mark eligible Ongoing steps incomplete and clear execution markers."""
    flow_path = Path(workspace_dir) / "home" / "flow.json"
    source = json_read(flow_path)
    if not isinstance(source, dict):
        raise OSError(f"failed to read Workspace flow: {flow_path}")
    updated = deepcopy(source)
    recovered: list[str] = []
    for step in updated.get("steps", []):
        if not isinstance(step, dict) or step.get("state") != StateEnum.Ongoing.value:
            continue
        info = step.get("info") if isinstance(step.get("info"), dict) else {}
        execution = info.get("execution")
        legacy = info.get("runtime_operation")
        eligible = False
        if isinstance(execution, dict):
            marker_run_id = execution.get("run_id")
            eligible = (
                execution.get("schema_version") == 1
                and isinstance(marker_run_id, str)
                and bool(marker_run_id)
                and (run_id is None or marker_run_id == run_id)
            )
        elif isinstance(legacy, dict):
            marker_id = legacy.get("operation_id")
            eligible = run_id is None or marker_id == run_id
        elif allow_markerless:
            eligible = True
        if not eligible:
            continue
        step["state"] = StateEnum.Imcomplete.value
        info.pop("execution", None)
        info.pop("runtime_operation", None)
        recovered.append(str(step.get("name", "")))
    if recovered and not json_write(flow_path, updated):
        raise OSError(f"failed to save recovered flow state: {flow_path}")
    return tuple(recovered)
