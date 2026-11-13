"""Shared EngineFlow completion hooks."""

import logging
from pathlib import Path
from typing import Literal

from chipcompiler.data.workspace.flow_types import ChecklistStatus

logger = logging.getLogger(__name__)


def summarize_step_checklist(workspace_step) -> ChecklistStatus | None:
    """Return a compact checklist gate projection for flow.json."""
    path = getattr(getattr(workspace_step, "checklist", None), "path", None)
    if not path:
        return None
    try:
        from chipcompiler.utility import json_read

        data = json_read(Path(path))
    except (OSError, TypeError, ValueError):
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("checklist"), list):
        return {
            "status": "unknown",
            "blocked": False,
            "failed_items": [],
            "source": _checklist_source(path),
        }
    raw_status = data.get("status")
    status_value: Literal["passed", "blocked", "attention", "unknown"]
    if raw_status == "ready":
        status_value = "passed"
    elif raw_status == "blocked":
        status_value = "blocked"
    elif raw_status == "attention":
        status_value = "attention"
    else:
        status_value = "unknown"
    failed_items = [
        item.get("id") or item.get("title", "")
        for item in data["checklist"]
        if isinstance(item, dict) and item.get("blocked") is True
    ]
    result: ChecklistStatus = {
        "status": status_value,
        "blocked": status_value == "blocked",
        "failed_items": failed_items,
        "source": _checklist_source(path),
    }
    if isinstance(data.get("summary"), dict):
        result["summary"] = dict(data["summary"])
    if data.get("requirements_status") in {"none", "present"}:
        result["requirements_status"] = data["requirements_status"]
    if isinstance(data.get("checker_revision"), str):
        result["revision"] = data["checker_revision"]
    if isinstance(data.get("generated_at"), str):
        result["updated_at"] = data["generated_at"]
    return result


def _checklist_source(path: Path) -> str:
    workspace_root = path.parent.parent
    if (workspace_root / "home").is_dir():
        try:
            return path.relative_to(workspace_root).as_posix()
        except ValueError:
            pass
    return str(path)


def sync_step_checklist(flow, workspace_step) -> ChecklistStatus | None:
    """Persist checklist projection before publishing step completion."""
    projection = summarize_step_checklist(workspace_step)
    if projection is None:
        return None
    current = flow.get_step(workspace_step.name, workspace_step.tool)
    if current is None:
        return projection
    current.pop("checklist", None)
    current["checklist_status"] = projection
    if not flow.save():
        raise RuntimeError(
            "failed to persist checklist projection for "
            f"{workspace_step.name}/{workspace_step.tool}"
        )
    return projection


def reset_unfinished_terminal_state(flow, workspace_step, step_tag) -> None:
    """Reset current unfinished terminal states before a rerun."""
    old_step = flow.get_step(name=workspace_step.name, tool=workspace_step.tool)
    if old_step is None:
        return
    if old_step.get("state") == "Warning":
        raise ValueError(f"{step_tag} uses the removed Warning state; create a new workspace")
    persisted = old_step.get("state")
    if persisted in {"Incomplete", "Invalid"}:
        logger.warning(
            "Resetting %s state '%s' -> Unstart",
            step_tag,
            persisted,
        )
        old_step["state"] = "Unstart"
        old_step["runtime"] = ""
        old_step["peak memory (mb)"] = 0
        old_step.pop("resource_observation", None)


def finalize_interrupted_subflow(workspace_step, runtime, peak_memory_mb) -> list[dict]:
    """Mark the step's running subflow stages Incomplete; return them for the observer."""
    try:
        from chipcompiler.engine.subflow_events import finalize_interrupted_subflow as finalize

        return finalize(workspace_step, runtime, peak_memory_mb)
    except (Exception, SystemExit):
        logger.exception("Failed to finalize subflow after %s", workspace_step.name)
        return []


def refresh_signoff_checklist(workspace, workspace_step) -> None:
    """Replace step/home checklists after the step's terminal flow state is saved."""
    try:
        from chipcompiler.tools.ecc.signoff_checklist import refresh_step_checklist

        refresh_step_checklist(workspace, workspace_step)
    except (Exception, SystemExit):
        logger.exception(
            "Failed to refresh signoff checklist after %s/%s",
            workspace_step.name,
            workspace_step.tool,
        )


def refresh_qor_report(workspace, step_tag: str) -> None:
    """Refresh the inspection report without changing flow completion policy."""
    try:
        from chipcompiler.analysis.qor import refresh_workspace_qor_report

        refresh_workspace_qor_report(workspace)
    except Exception:
        workspace.logger.exception("[QOR] %s failed to refresh the workspace QoR report", step_tag)
