"""Typed operation orchestrator for CLI/headless EDA execution via worker.

Integrates WorkerClient, LogStreamReader, process-group cleanup, and
flow-state repair into one typed OperationResult boundary. All EDA
execution from CLI entry points should go through RunOperation.
"""

import sys
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from chipcompiler.runtime.log_stream import LogStreamReader, LogStreamState
from chipcompiler.runtime.worker import (
    WorkerClient,
    WorkerResult,
    classify_worker_exit,
    repair_flow_state,
)


@dataclass(frozen=True)
class OperationResult:
    """Typed outcome of a single worker operation (run or run_step)."""

    success: bool
    rpc_result: dict | None = None
    exit_code: int | None = None
    signal_number: int | None = None
    error: str | None = None
    repaired_steps: list[str] = field(default_factory=list)
    archive_error: Exception | None = field(default=None, repr=False)
    log_state: LogStreamState | None = field(default=None, repr=False)


class RunOperation:
    """Orchestrates a single EDA flow execution through an isolated worker.

    Usage:
        op = RunOperation(
            workspace_dir=Path("/path/to/workspace"),
            flow_json_path=Path("/path/to/flow.json"),
            log_path_resolver=my_resolver,
        )
        result = op.run(method="flow.run", params={...})
    """

    def __init__(
        self,
        *,
        workspace_dir: Path,
        flow_json_path: Path,
        worker_argv: list[str] | None = None,
        log_path_resolver: Callable[[str, str], Path | None] | None = None,
        on_output: Callable[[bytes], None] | None = None,
    ):
        self._workspace_dir = workspace_dir
        self._flow_json_path = flow_json_path
        self._worker_argv = worker_argv or [
            sys.executable,
            "-m",
            "chipcompiler.runtime.stdio_server",
            "--workspace",
            str(workspace_dir),
        ]
        self._log_path_resolver = log_path_resolver
        self._on_output = on_output

    def run(self, method: str, params: dict, *, request_id: int = 1) -> OperationResult:
        """Execute one RPC method against the worker and return a typed result."""
        client = WorkerClient(self._worker_argv)
        active_step: str | None = None

        try:
            proc = client.start()

            reader = LogStreamReader(
                proc.stderr,
                log_path_resolver=self._log_path_resolver,
                on_output=self._on_output,
            )
            reader.start()

            try:
                rpc_result = client.request(method, params, request_id)
            except KeyboardInterrupt:
                return self._handle_crash(client, reader, active_step, "operation interrupted")

            reader.stop()
            reader.join(timeout=5.0)

            log_state = reader.state
            archive_error = log_state.error
            active_step = log_state.active_step

            if not rpc_result.success:
                if not client.is_alive():
                    return self._handle_crash(
                        client, reader, active_step, rpc_result.error or "worker crashed"
                    )
                exit_result = self._shutdown(client)
                return OperationResult(
                    success=False,
                    rpc_result=rpc_result.response,
                    exit_code=exit_result.exit_code,
                    signal_number=exit_result.signal_number,
                    error=rpc_result.error,
                    archive_error=archive_error,
                    log_state=log_state,
                )

            exit_result = self._shutdown(client)

            return OperationResult(
                success=exit_result.exit_code == 0 or exit_result.exit_code is None,
                rpc_result=rpc_result.response,
                exit_code=exit_result.exit_code,
                signal_number=exit_result.signal_number,
                error=exit_result.error if exit_result.exit_code not in (0, None) else None,
                archive_error=archive_error,
                log_state=log_state,
            )

        except Exception as exc:
            return self._handle_crash(client, None, active_step, str(exc))

    def _shutdown(self, client: WorkerClient) -> WorkerResult:
        """Clean shutdown: terminate process group and classify exit."""
        client.terminate()
        proc = client.process
        if proc is None:
            return WorkerResult(success=True, exit_code=0)
        return classify_worker_exit(proc)

    def _handle_crash(
        self,
        client: WorkerClient,
        reader: LogStreamReader | None,
        active_step: str | None,
        error: str,
    ) -> OperationResult:
        """Crash recovery: terminate, drain, repair, return failure."""
        exit_code: int | None = None
        signal_number: int | None = None
        repaired: list[str] = []
        log_state: LogStreamState | None = None
        archive_error: Exception | None = None

        try:
            client.terminate()
            proc = client.process
            if proc is not None:
                exit_result = classify_worker_exit(proc)
                exit_code = exit_result.exit_code
                signal_number = exit_result.signal_number
        except Exception:
            pass

        if reader is not None:
            reader.join(timeout=2.0)
            reader.stop()
            log_state = reader.state
            archive_error = log_state.error
            if active_step is None:
                active_step = log_state.active_step

        if active_step is not None and self._flow_json_path.exists():
            with suppress(OSError):
                repaired = repair_flow_state(self._flow_json_path, active_step=active_step)

        return OperationResult(
            success=False,
            exit_code=exit_code,
            signal_number=signal_number,
            error=error,
            repaired_steps=repaired,
            archive_error=archive_error,
            log_state=log_state,
        )
