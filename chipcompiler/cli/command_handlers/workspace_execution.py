"""Inspect and configure workspace-local execution policy."""

from pathlib import Path

from chipcompiler.cli.core.records import error_record
from chipcompiler.cli.core.types import CommandContext, CommandResult
from chipcompiler.data.workspace.execution import declared_step_subprocess
from chipcompiler.engine.snapshot.store import EngineeringSnapshotError, read_engineering_snapshot
from chipcompiler.engine.step.process import execution_mode
from chipcompiler.engine.workspace.lifecycle import (
    WorkspaceLifecycleError,
    _load_committed_workspace,
)
from chipcompiler.engine.workspace_execution import update_workspace_execution


def workspace_execution(args, ctx: CommandContext) -> CommandResult:
    if ctx.manifest_error:
        return CommandResult.err(
            [error_record("workspace_not_declared", reason=ctx.manifest_error)]
        )
    try:
        if args.step_subprocess is None:
            workspace = _load_committed_workspace(Path(ctx.run_dir))
        else:
            workspace = update_workspace_execution(
                ctx.run_dir,
                step_subprocess=args.step_subprocess,
                expected_revision=args.expected_revision,
                command_id=args.command_id,
                blocking=not args.no_wait,
            )
        stored = declared_step_subprocess(workspace.flow.data)
        effective, source = execution_mode(workspace)
        snapshot = read_engineering_snapshot(workspace)
    except BlockingIOError:
        return CommandResult.err([error_record("workspace_busy")], exit_code=20)
    except (WorkspaceLifecycleError, EngineeringSnapshotError, ValueError, OSError) as exc:
        code = (
            exc.code if isinstance(exc, WorkspaceLifecycleError) else "workspace_execution_failed"
        )
        return CommandResult.err(
            [error_record(code, reason=str(exc))],
            exit_code=21 if code == "revision_conflict" else 1,
        )
    return CommandResult.ok(
        [
            {
                "record": "workspace_execution",
                "workspace_id": ctx.run_id,
                "workspace": ctx.run_dir,
                "workspace_revision": snapshot["workspaceRevision"],
                "step_subprocess": True if stored is None else stored,
                "configured": stored is not None,
                "effective_step_subprocess": effective,
                "source": source,
            }
        ]
    )
