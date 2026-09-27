"""Manifest runtime-process lifecycle for one locked ECC run."""

from __future__ import annotations

import os
import signal
import sys
import threading
from contextlib import contextmanager, suppress

from chipcompiler.project.runtime_processes import (
    RuntimeProcessError,
    build_runtime_entry,
    create_run_log,
    normalize_log_path,
    normalize_run_id,
    normalize_runtime_id,
    register_runtime_process,
    unregister_runtime_process,
)


@contextmanager
def managed_run_process(
    command_input, project_dir, workspace_id, workspace, *, workspace_path: str
):
    """Register this process and expose its execution marker to Engine."""
    from chipcompiler import __version__

    run_id = normalize_run_id(command_input.run_id)
    runtime_id = normalize_runtime_id(
        command_input.runtime_id,
        default=f"external:{__version__}",
    )
    log_path = normalize_log_path(command_input.log_file, run_id)
    log_descriptor = create_run_log(workspace_path, log_path)
    cancel_event = threading.Event()
    old_handler = None
    registered = False
    old_run_id = getattr(workspace, "_ecc_run_id", None)
    old_cancel_event = getattr(workspace, "_ecc_cancel_event", None)
    try:
        _ensure_process_group_leader()
        old_handler = signal.getsignal(signal.SIGUSR1)
        signal.signal(signal.SIGUSR1, lambda _signum, _frame: cancel_event.set())
        entry = build_runtime_entry(
            project_dir,
            workspace_path,
            run_id=run_id,
            runtime_id=runtime_id,
            log_path=log_path,
        )
        register_runtime_process(
            project_dir,
            workspace_id,
            entry,
            blocking=not command_input.no_wait,
        )
        registered = True
        workspace._ecc_run_id = run_id
        workspace._ecc_cancel_event = cancel_event
        os.write(log_descriptor, f"ECC run {run_id} started\n".encode())
        with _redirect_stdio_to_descriptor(
            log_descriptor, enabled=bool(command_input.log_file)
        ):
            yield entry
    finally:
        if registered:
            try:
                os.write(log_descriptor, f"ECC run {run_id} finished\n".encode())
                os.fsync(log_descriptor)
                unregister_runtime_process(project_dir, workspace_id, run_id)
            except Exception as exc:  # Final flow state remains authoritative.
                with suppress(OSError):
                    os.write(
                        log_descriptor,
                        f"WARNING: failed to unregister runtime process: {exc}\n".encode(),
                    )
                    os.fsync(log_descriptor)
        if old_run_id is None:
            workspace.__dict__.pop("_ecc_run_id", None)
        else:
            workspace._ecc_run_id = old_run_id
        if old_cancel_event is None:
            workspace.__dict__.pop("_ecc_cancel_event", None)
        else:
            workspace._ecc_cancel_event = old_cancel_event
        if old_handler is not None:
            signal.signal(signal.SIGUSR1, old_handler)
        os.close(log_descriptor)


@contextmanager
def _redirect_stdio_to_descriptor(descriptor: int, *, enabled: bool):
    """Capture a detached GUI run without leaving a pipe owned by Electron."""
    if not enabled:
        yield
        return
    from chipcompiler.utility.log import flush_cstdio

    saved_fds = (os.dup(1), os.dup(2))
    saved_streams = (sys.stdout, sys.stderr)
    try:
        for stream in saved_streams:
            with suppress(Exception):
                stream.flush()
        flush_cstdio()
        os.dup2(descriptor, 1)
        os.dup2(descriptor, 2)
        sys.stdout = os.fdopen(1, "w", encoding="utf-8", buffering=1, closefd=False)
        sys.stderr = os.fdopen(2, "w", encoding="utf-8", buffering=1, closefd=False)
        yield
    finally:
        for stream in (sys.stdout, sys.stderr):
            with suppress(Exception):
                stream.flush()
        flush_cstdio()
        os.dup2(saved_fds[0], 1)
        os.dup2(saved_fds[1], 2)
        os.close(saved_fds[0])
        os.close(saved_fds[1])
        sys.stdout, sys.stderr = saved_streams


def runtime_process_error_result(exc: RuntimeProcessError, *, workspace_id: str, workspace: str):
    from chipcompiler.cli.core.records import error_record
    from chipcompiler.cli.core.types import CommandResult

    code = 20 if exc.code in {"workspace_running"} else 1
    return CommandResult.err(
        [
            error_record(
                exc.code,
                workspace_id=workspace_id,
                workspace=workspace,
                reason=str(exc),
            )
        ],
        exit_code=code,
    )


def _ensure_process_group_leader() -> None:
    pid = os.getpid()
    if os.getpgid(pid) != pid:
        try:
            os.setpgid(0, 0)
        except OSError as exc:
            raise RuntimeProcessError(
                "invalid_process_group", "ECC run must own an independent process group"
            ) from exc
    if os.getpgid(pid) != pid:
        raise RuntimeProcessError(
            "invalid_process_group", "ECC run must own an independent process group"
        )
