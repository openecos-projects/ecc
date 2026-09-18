"""Resolve per-step output artifacts for a workspace on disk.

The GUI "create workspace from step output" flow needs the real artifact
paths a step produces. Those paths are owned by the tool builders, so this
module derives them through the same builder chain the engine runs with
instead of re-encoding directory or filename conventions per consumer.
"""

from pathlib import Path
from typing import Any

from chipcompiler.engine.workspace_flow import iter_workspace_steps


def _artifact(path: Any) -> dict[str, Any] | None:
    if not path:
        return None
    candidate = Path(path)
    return {"path": str(candidate), "exists": candidate.is_file()}


def resolve_workspace_step_outputs(workspace, step: str = "") -> dict[str, Any]:
    """Resolve output artifacts for one committed flow step or all of them.

    ``step`` filters by flow step name; an empty value resolves every step
    recorded in the workspace flow ledger, in flow order. Steps whose tool
    builder cannot be constructed are still listed, with null artifacts.
    """
    flow = getattr(workspace, "flow", None)
    raw_steps = flow.steps() if flow is not None else []
    names = [str(raw.get("name")) for raw in raw_steps if raw.get("name")]
    if step and step not in names:
        raise ValueError(f"flow step not found: {step}")

    states = {
        str(raw.get("name")): str(raw.get("state", "")) for raw in raw_steps if raw.get("name")
    }
    steps: list[dict[str, Any]] = []
    for flow_step, workspace_step in iter_workspace_steps(workspace):
        name = str(flow_step.get("name") or "")
        if not name or (step and name != step):
            continue
        output = getattr(workspace_step, "output", None)
        steps.append(
            {
                "step": name,
                "tool": str(getattr(workspace_step, "tool", "") or ""),
                "state": states.get(name, ""),
                "verilog": _artifact(getattr(output, "verilog", None)),
                "def": _artifact(getattr(output, "def_", None)),
            }
        )

    sdc = getattr(getattr(workspace, "pdk", None), "sdc", None)
    return {
        "directory": str(Path(workspace.directory).resolve()),
        "design": str(getattr(getattr(workspace, "design", None), "name", "")),
        "sdc": _artifact(sdc),
        "steps": steps,
    }
