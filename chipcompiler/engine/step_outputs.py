"""Build the persisted per-step output projection for a Workspace."""

from pathlib import Path
from typing import Any

from chipcompiler.engine.workspace_flow import iter_workspace_steps


def _artifact(path: Any, workspace_root: Path) -> dict[str, Any] | None:
    if not path:
        return None
    candidate = Path(path).expanduser()
    absolute = candidate if candidate.is_absolute() else workspace_root / candidate
    absolute = absolute.resolve(strict=False)
    try:
        reference = str(absolute.relative_to(workspace_root))
    except ValueError:
        reference = str(absolute)
    return {"path": reference, "exists": absolute.is_file()}


def resolve_workspace_step_outputs(workspace: Any, step: str = "") -> dict[str, Any]:
    """Resolve output artifacts for one committed flow step or all of them."""
    workspace_root = Path(workspace.directory).resolve()
    flow = getattr(workspace, "flow", None)
    raw_steps = flow.steps() if flow is not None and hasattr(flow, "steps") else []
    if not raw_steps:
        data = getattr(flow, "data", {})
        raw_steps = data.get("steps", []) if isinstance(data, dict) else []
    names = [str(raw.get("name")) for raw in raw_steps if raw.get("name")]
    if step and step not in names:
        raise ValueError(f"flow step not found: {step}")

    states = {
        str(raw.get("name")): str(raw.get("state", "")) for raw in raw_steps if raw.get("name")
    }
    steps: list[dict[str, Any]] = []
    try:
        workspace_steps = iter_workspace_steps(workspace)
        for flow_step, workspace_step in workspace_steps:
            name = str(flow_step.get("name") or "")
            if not name or (step and name != step):
                continue
            output = getattr(workspace_step, "output", None)
            steps.append(
                {
                    "step": name,
                    "tool": str(getattr(workspace_step, "tool", "") or ""),
                    "state": states.get(name, ""),
                    "verilog": _artifact(getattr(output, "verilog", None), workspace_root),
                    "def": _artifact(getattr(output, "def_", None), workspace_root),
                }
            )
    except (AttributeError, KeyError, TypeError, ValueError):
        # Partially migrated Workspaces may not have enough configuration to
        # construct builders. Keep their known flow order visible to repair UI.
        steps = [
            {
                "step": name,
                "tool": str(raw.get("tool", "")),
                "state": states.get(name, ""),
                "verilog": None,
                "def": None,
            }
            for raw in raw_steps
            if (name := str(raw.get("name") or "")) and (not step or name == step)
        ]

    sdc = getattr(getattr(workspace, "pdk", None), "sdc", None)
    return {
        "directory": ".",
        "design": str(getattr(getattr(workspace, "design", None), "name", "")),
        "sdc": _artifact(sdc, workspace_root),
        "steps": steps,
    }
