"""Shared EngineFlow completion hooks."""

import logging
from copy import deepcopy

logger = logging.getLogger(__name__)


def normalize_legacy_terminal_state(flow, workspace_step, step_tag) -> None:
    """Reset terminal states from pre-guard workspaces before rerun."""
    old_step = flow.get_step(name=workspace_step.name, tool=workspace_step.tool)
    if old_step is None:
        return
    persisted = old_step.get("state")
    if persisted in {"Incomplete", "Invalid", "Warning"}:
        logger.warning(
            "Normalizing legacy %s state '%s' -> Unstart",
            step_tag,
            persisted,
        )
        old_step["state"] = "Unstart"
        old_step["runtime"] = ""
        old_step["peak memory (mb)"] = 0


def finalize_interrupted_subflow(observer, workspace_step, runtime, peak_memory_mb) -> None:
    try:
        from chipcompiler.runtime.subflow_events import finalize_interrupted_subflow as finalize

        for subflow_step in finalize(workspace_step, runtime, peak_memory_mb):
            notify_flow_observer(observer, "on_subflow_stage", workspace_step, subflow_step)
    except (Exception, SystemExit):
        logger.exception("Failed to finalize subflow after %s", workspace_step.name)


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


def notify_flow_observer(observer, method_name: str, *args) -> None:
    """Keep optional GUI observers outside the flow engine's failure domain."""
    if observer is None:
        return
    callback = getattr(observer, method_name, None)
    if not callable(callback):
        return
    try:
        callback(*args)
    except (Exception, SystemExit):
        if getattr(observer, "fatal_observer", False):
            raise
        logger.exception("flow observer callback failed: %s", method_name)


def notify_step_completed(
    flow,
    observer,
    workspace_step,
    state,
    error,
    previous_step: dict | None,
) -> None:
    """Publish completion and restore Ongoing state when a fatal commit fails."""
    try:
        notify_flow_observer(observer, "on_step_completed", workspace_step, state, error)
    except (Exception, SystemExit):
        if previous_step is not None:
            current = flow.get_step(workspace_step.name, workspace_step.tool)
            if current is not None:
                current.clear()
                current.update(deepcopy(previous_step))
                if not flow.save():
                    raise RuntimeError(
                        "failed to roll back flow state after completion commit failure"
                    ) from None
        raise
