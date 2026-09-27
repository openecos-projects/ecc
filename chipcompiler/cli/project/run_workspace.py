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


def execute_workspace_run(
    command_input,
    workspace_path: str,
    workspace_id: str | None = None,
    *,
    project_dir: str | None = None,
) -> CommandResult:
    """Reconcile and execute a registered project workspace.

    Selector validity was already checked by the handler. Explicit
    selectors (--from/--only) re-execute on request; the default resume
    runs only within the reconciled target range. Manifest projects register
    the active process in project.json without writing flow status there.
    """
    from chipcompiler.cli.project.run_process import run_log_stdio
    from chipcompiler.project.runtime_processes import RuntimeProcessError

    workspace_path = os.path.abspath(workspace_path)
    try:
        # §13.1 step 2: an explicit --log-file must exist and own stdout/
        # stderr before the pure-read preflight below; a log-open failure
        # exits here without running the flow.
        with run_log_stdio(command_input, workspace_path) as run_log:
            return _execute_workspace_run(
                command_input,
                workspace_path,
                workspace_id,
                project_dir=project_dir,
                run_log=run_log,
            )
    except RuntimeProcessError as exc:
        from chipcompiler.cli.project.run_process import runtime_process_error_result

        return runtime_process_error_result(
            exc,
            workspace_id=workspace_id or "default",
            workspace=workspace_path,
        )


def _execute_workspace_run(
    command_input,
    workspace_path: str,
    workspace_id: str | None,
    *,
    project_dir: str | None,
    run_log,
) -> CommandResult:
    from chipcompiler.data import load_workspace
    from chipcompiler.data.schema_migrations import UnsupportedSchemaVersionError
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

    warnings: list[dict] = []

    def error(kind: str, **fields) -> CommandResult:
        return CommandResult.err(warnings + [{"kind": "error", "error": kind, **fields}])

    workspace_path = os.path.abspath(workspace_path)

    from chipcompiler.cli.project.pdk_root_fallback import pdk_root_env_fallback_warning
    from chipcompiler.cli.project.spec_drift import workspace_spec_drift_warning

    pdk_root_warning = pdk_root_env_fallback_warning(workspace_path)
    if pdk_root_warning is not None:
        warnings.append(pdk_root_warning)
    spec_drift = workspace_spec_drift_warning(workspace_path)
    if spec_drift is not None:
        warnings.append(spec_drift)

    def mismatch_error(reason: str) -> CommandResult:
        if reason.startswith("unsupported_schema_version"):
            return error("unsupported_schema_version", workspace=workspace_path, reason=reason)
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
    # can migrate configs, create checklist state, or take the lock.
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
    with _workspace_lock(Path(workspace_path), blocking=not command_input.no_wait):
        from chipcompiler.cli.project.revision import expected_revision_error

        conflict = expected_revision_error(
            workspace_path,
            command_input.expected_revision,
            workspace_id=workspace_id,
        )
        if conflict is not None:
            return conflict
        # Re-probe under the lock: a concurrent reconcile may have changed
        # the classification since the preflight read.
        probe = classify_workspace(workspace_path)
        if probe.outcome == "mismatch":
            return mismatch_error(probe.error or "")

        try:
            workspace = load_workspace(workspace_path)
        except UnsupportedSchemaVersionError as exc:
            return error("unsupported_schema_version", workspace=workspace_path, reason=str(exc))
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
            # The persisted flow already covers the target and finished;
            # resume has nothing to do. Explicit selectors (--from/--only)
            # still re-execute on request. The flow is complete, so the
            # manifest entry reads success even if a previous failed state
            # is stale.
            return CommandResult.ok(
                warnings
                + [
                    {
                        "workspace_id": workspace_id or "default",
                        "status": "success",
                        "workspace": workspace_path,
                        "executed_steps": [],
                        "no_op": True,
                    }
                ]
            )

        def run_failed(kind: str, reason: str | None = None) -> CommandResult:
            return CommandResult.err(
                warnings
                + [
                    {
                        "kind": "error",
                        "error": kind,
                        "workspace": workspace_path,
                        **({"reason": reason} if reason else {}),
                    }
                ]
            )

        try:
            from contextlib import nullcontext

            if project_dir is not None and workspace_id:
                from chipcompiler.cli.project.run_process import managed_run_process

                process_context = managed_run_process(
                    command_input,
                    project_dir,
                    workspace_id,
                    workspace,
                    workspace_path=workspace_path,
                    run_log=run_log,
                )
            else:
                process_context = nullcontext()
            with process_context:
                engine_flow = EngineFlow(workspace=workspace)
                if not engine_flow.has_init():
                    return run_failed("missing_flow")

                try:
                    selected = rerun.selected_step_names(
                        engine_flow,
                        from_step=command_input.from_step,
                        through=command_input.to_step,
                        only=command_input.only,
                        force=command_input.force,
                    )
                    if command_input.from_step is None and command_input.only is None:
                        target_names = reconcile_result.target
                        if target_names:
                            selected = rerun.bounded_resume_names(engine_flow, target_names[-1])
                except ValueError as exc:
                    return run_failed("unknown_step", str(exc))

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
                            result = rerun.run_from(
                                engine_flow,
                                command_input.from_step,
                                through=command_input.to_step,
                            )
                        elif reconcile_result.target:
                            result = rerun.run_resume(
                                engine_flow, through=reconcile_result.target[-1]
                            )
                        else:
                            result = rerun.run_resume(engine_flow)
                except ValueError as exc:
                    return run_failed("step_unavailable", str(exc))
        except Exception as exc:
            from chipcompiler.project.runtime_processes import RuntimeProcessError

            if isinstance(exc, RuntimeProcessError):
                from chipcompiler.cli.project.run_process import runtime_process_error_result

                return runtime_process_error_result(
                    exc,
                    workspace_id=workspace_id or "default",
                    workspace=workspace_path,
                )
            return run_failed("flow_failed", str(exc))
    record = {
        "workspace_id": workspace_id or "default",
        "status": "success" if result.ok else "failed",
        "workspace": workspace_path,
        "executed_steps": list(result.executed),
        "no_op": result.ok and not result.executed,
    }
    if result.ok:
        return CommandResult.ok(warnings + [record])
    record["failed_step"] = result.failed
    record["resume_cmd"] = f"ecc run --workspace {shlex.quote(workspace_id or 'default')} --resume"
    return CommandResult.err(warnings + [record])
