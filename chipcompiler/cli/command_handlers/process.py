"""CLI adapters for detached ECC process control."""

from chipcompiler.cli.core.records import error_record, manifest_error_record
from chipcompiler.cli.core.types import CommandResult
from chipcompiler.project.runtime_processes import RuntimeProcessError


def inspect_process(command_input, ctx) -> CommandResult:
    failure = _workspace_failure(command_input, ctx)
    if failure is not None:
        return failure
    from chipcompiler.project.process_control import inspect_process as inspect

    return _invoke(
        lambda: inspect(ctx.project_dir, ctx.run_id, command_input.run_id),
        ctx.run_id,
        "alive",
    )


def cancel_process(command_input, ctx) -> CommandResult:
    failure = _workspace_failure(command_input, ctx)
    if failure is not None:
        return failure
    from chipcompiler.project.process_control import cancel_process as cancel

    return _invoke(
        lambda: cancel(
            ctx.project_dir,
            ctx.run_id,
            command_input.run_id,
            force=command_input.force,
        ),
        ctx.run_id,
        "cancel_requested",
    )


def reconcile_process(command_input, ctx) -> CommandResult:
    failure = _workspace_failure(command_input, ctx)
    if failure is not None:
        return failure
    from chipcompiler.project.process_control import reconcile_process as reconcile

    try:
        recovered = reconcile(
            ctx.project_dir,
            ctx.run_id,
            command_input.run_id,
            blocking=not command_input.no_wait,
        )
    except BlockingIOError:
        return CommandResult.err([error_record("workspace_busy")], exit_code=20)
    except RuntimeProcessError as exc:
        return _error(exc)
    except Exception as exc:
        return CommandResult.err([error_record("process_reconcile_failed", reason=str(exc))])
    return CommandResult.ok(
        [
            {
                "workspace_id": ctx.run_id,
                "status": "reconciled",
                "recovered_steps": list(recovered),
            }
        ]
    )


def _invoke(callback, workspace_id: str, status: str) -> CommandResult:
    try:
        entry = callback()
    except RuntimeProcessError as exc:
        return _error(exc)
    except Exception as exc:
        return CommandResult.err([error_record("process_control_failed", reason=str(exc))])
    return CommandResult.ok(
        [
            {
                "workspace_id": workspace_id,
                "run_id": entry["run_id"],
                "pid": entry["pid"],
                "status": status,
            }
        ]
    )


def _workspace_failure(command_input, ctx) -> CommandResult | None:
    if ctx.manifest_error:
        return CommandResult.err([manifest_error_record(ctx.manifest_error)])
    if command_input.workspace is None or ctx.run_id is None:
        return CommandResult.err(
            [
                error_record(
                    "workspace_required", reason="provide --workspace or run inside a workspace"
                )
            ]
        )
    return None


def _error(exc: RuntimeProcessError) -> CommandResult:
    if exc.code == "workspace_busy":
        return CommandResult.err([error_record(exc.code, reason=str(exc))], exit_code=20)
    if exc.code in {
        "process_not_found",
        "process_identity_changed",
        "invalid_runtime_process",
    }:
        return CommandResult.err([error_record(exc.code, reason=str(exc))], exit_code=22)
    return CommandResult.err([error_record(exc.code, reason=str(exc))])
