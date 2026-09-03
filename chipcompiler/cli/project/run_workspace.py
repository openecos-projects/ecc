#!/usr/bin/env python

"""Explicit ``ecc run --workspace`` execution.

The command handler validates selectors; this module owns the workspace
lifecycle under the sibling workspace lock (``<workspace>.lock``):
re-probe, load, reconcile against the workspace's persisted target, and
execute — the default resume bounded to the reconciled target so a wider
persisted ledger is never re-run or invalidated past it. Two runs of the
same workspace (or an overwrite/migration replacing it) serialize on the
lock. Imported lazily by the run handler; keep module-level imports cheap.
"""

import os
import shlex
from pathlib import Path

from chipcompiler.cli.core.types import CommandResult


def execute_workspace_run(command_input) -> CommandResult:
    """Reconcile and execute an explicit workspace target.

    Selector validity was already checked by the handler. Explicit
    selectors (--from/--only) re-execute on request; the default resume
    runs only within the reconciled target range.
    """
    from chipcompiler.data import load_workspace
    from chipcompiler.data.workspace_config import (
        WorkspaceConfigError,
        WorkspaceFlowTargetError,
    )
    from chipcompiler.engine import EngineFlow, rerun
    from chipcompiler.engine.reconcile import (
        _workspace_lock,
        classify_workspace,
        reconcile_workspace_locked,
    )

    def error(kind: str, **fields) -> CommandResult:
        return CommandResult.err([{"kind": "error", "error": kind, **fields}])

    workspace_path = os.path.abspath(os.path.expanduser(command_input.workspace))

    def mismatch_error(reason: str) -> CommandResult:
        if reason.startswith("workspace_config_invalid"):
            return error("workspace_config_invalid", workspace=workspace_path, reason=reason)
        if reason.startswith("flow_adopt_failed"):
            return error("flow_adopt_failed", workspace=workspace_path, reason=reason)
        return error(
            "flow_mismatch",
            workspace=workspace_path,
            reason="the workspace flow target diverges from the persisted flow",
        )

    # Pure-read preflight: a divergent flow is rejected BEFORE load_workspace
    # can migrate configs, create home.json/checklist, or take the lock.
    probe = classify_workspace(workspace_path)
    if probe.outcome == "mismatch":
        return mismatch_error(probe.error or "")

    # An absent workspace fails before the lock: taking the sibling lock
    # would create the lock file (and its parent directories) for a command
    # that has nothing to run — a failed command must not mutate the tree.
    if not os.path.isdir(workspace_path):
        return error("invalid_workspace", workspace=workspace_path)

    # Everything from here holds the workspace lock: two runs of the same
    # workspace never execute concurrently, and an overwrite or migration
    # replacing the tree serializes against this execution.
    with _workspace_lock(Path(workspace_path)):
        # Re-probe under the lock: a concurrent reconcile may have changed
        # the classification since the preflight read.
        probe = classify_workspace(workspace_path)
        if probe.outcome == "mismatch":
            return mismatch_error(probe.error or "")

        try:
            workspace = load_workspace(workspace_path)
        except (WorkspaceConfigError, WorkspaceFlowTargetError) as exc:
            return error("workspace_config_invalid", workspace=workspace_path, reason=str(exc))
        except Exception as exc:
            return error("invalid_workspace", workspace=workspace_path, reason=str(exc))
        if workspace is None:
            return error("invalid_workspace", workspace=workspace_path)

        # Extend/resume against the workspace's own persisted flow target
        # before building the engine flow, so appended steps are visible.
        reconcile_result = reconcile_workspace_locked(workspace_path)
        if not reconcile_result.ok:
            return mismatch_error(reconcile_result.error or "")
        if (
            reconcile_result.outcome == "no_op"
            and reconcile_result.persisted
            and command_input.from_step is None
            and command_input.only is None
        ):
            # The persisted flow already covers the target and succeeded;
            # resume has nothing to do. Explicit selectors (--from/--only)
            # still re-execute on request.
            return CommandResult.ok(
                [
                    {
                        "run": "workspace",
                        "status": "success",
                        "workspace": workspace_path,
                        "executed_steps": [],
                        "no_op": True,
                    }
                ]
            )

        try:
            engine_flow = EngineFlow(workspace=workspace)
        except Exception as exc:
            return error("invalid_workspace", workspace=workspace_path, reason=str(exc))
        if not engine_flow.has_init():
            return error("missing_flow", workspace=workspace_path)

        try:
            selected = rerun.selected_step_names(
                engine_flow,
                from_step=command_input.from_step,
                only=command_input.only,
                force=command_input.force,
            )
            if command_input.from_step is None and command_input.only is None:
                # The default resume is bounded to the reconciled target:
                # steps beyond it are never selected, invalidated, or
                # re-executed, however wide the persisted ledger is.
                target_names = reconcile_result.target
                if target_names:
                    selected = rerun.bounded_resume_names(engine_flow, target_names[-1])
        except ValueError as exc:
            return error("unknown_step", workspace=workspace_path, reason=str(exc))

        from chipcompiler.cli.rendering.progress import preserve_cli_stdio

        try:
            with preserve_cli_stdio():
                if selected:
                    engine_flow.create_step_workspaces(executable_steps=set(selected))
                if command_input.only is not None:
                    result = rerun.run_only(
                        engine_flow, command_input.only, force=command_input.force
                    )
                elif command_input.from_step is not None:
                    result = rerun.run_from(engine_flow, command_input.from_step)
                elif reconcile_result.target:
                    result = rerun.run_resume(engine_flow, through=reconcile_result.target[-1])
                else:
                    result = rerun.run_resume(engine_flow)
        except ValueError as exc:
            return error("step_unavailable", workspace=workspace_path, reason=str(exc))
        except Exception as exc:
            return error("flow_failed", workspace=workspace_path, reason=str(exc))

    record = {
        "run": "workspace",
        "status": "success" if result.ok else "failed",
        "workspace": workspace_path,
        "executed_steps": list(result.executed),
        "no_op": result.ok and not result.executed,
    }
    if result.ok:
        return CommandResult.ok([record])
    record["failed_step"] = result.failed
    record["resume_cmd"] = f"ecc run --workspace {shlex.quote(workspace_path)} --resume"
    return CommandResult.err([record])
