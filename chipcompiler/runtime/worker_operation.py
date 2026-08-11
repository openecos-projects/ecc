"""Typed operation orchestrator for CLI/headless EDA execution via worker.

Integrates WorkerClient, LogStreamReader, process-group cleanup, and
flow-state repair into one typed OperationResult boundary. All EDA
execution from CLI entry points should go through RunOperation.
"""

import os
import subprocess
import sys
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from chipcompiler.runtime.log_stream import LogStreamReader, LogStreamState
from chipcompiler.runtime.worker import (
    WorkerClient,
    WorkerProcessError,
    WorkerResult,
    classify_worker_exit,
    repair_flow_state,
)

PROTOCOL_VERSION = 1


def _default_worker_argv() -> list[str]:
    ecc_bin = os.path.join(os.path.dirname(sys.executable), "ecc")
    return [ecc_bin, "rpc", "serve", "--stdio", "--persistent-db"]


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

    Implements the real session lifecycle:
    rpc.hello → workspace.open → caller's method → rpc.shutdown → EOF wait.

    Usage:
        op = RunOperation(
            workspace_dir=Path("/path/to/workspace"),
            flow_json_path=Path("/path/to/flow.json"),
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
        self._worker_argv = worker_argv or _default_worker_argv()
        self._log_path_resolver = log_path_resolver
        self._on_output = on_output

    def run(self, method: str, params: dict, *, request_id: int = 1) -> OperationResult:
        """Execute one RPC method against the worker and return a typed result.

        Session sequence: hello → workspace.open → method → rpc.shutdown → EOF.
        """
        client = WorkerClient(self._worker_argv)
        reader: LogStreamReader | None = None

        try:
            proc = client.start()

            reader = LogStreamReader(
                proc.stderr,
                log_path_resolver=self._log_path_resolver,
                on_output=self._on_output,
            )
            reader.start()

            hello_result = client.request("rpc.hello", {"version": PROTOCOL_VERSION}, request_id=0)
            if not hello_result.success:
                return self._handle_protocol_or_crash(client, reader, hello_result)

            open_result = client.request(
                "workspace.open",
                {"path": str(self._workspace_dir)},
                request_id=0,
            )
            if not open_result.success:
                return self._handle_protocol_or_crash(client, reader, open_result)

            rpc_result = client.request(method, params, request_id)

            if not rpc_result.success:
                if rpc_result.response is None or not client.is_alive():
                    error = rpc_result.error or "protocol failure"
                    return self._handle_crash(client, reader, error)
                # Live-worker RPC error: graceful shutdown then drain
                self._graceful_shutdown(client)
                reader.join(timeout=5.0)
                reader.stop()
                log_state = reader.state
                return OperationResult(
                    success=False,
                    rpc_result=rpc_result.response,
                    exit_code=client.process.returncode if client.process else None,
                    error=rpc_result.error,
                    archive_error=log_state.error,
                    log_state=log_state,
                )

            shutdown_ok = self._graceful_shutdown(client)

            reader.join(timeout=5.0)
            reader.stop()

            log_state = reader.state

            error_parts: list[str] = []
            if log_state.error is not None:
                error_parts.append(f"archive error: {log_state.error}")
            if not reader.completed:
                error_parts.append("log reader did not complete")
            if log_state.active_step is not None:
                error_parts.append(f"unmatched begin marker for step: {log_state.active_step}")
            if not shutdown_ok:
                error_parts.append("worker did not exit cleanly after shutdown")

            if error_parts:
                return OperationResult(
                    success=False,
                    rpc_result=rpc_result.response,
                    exit_code=client.process.returncode if client.process else None,
                    error="; ".join(error_parts),
                    archive_error=log_state.error,
                    log_state=log_state,
                )

            return OperationResult(
                success=True,
                rpc_result=rpc_result.response,
                exit_code=0,
                log_state=log_state,
            )

        except KeyboardInterrupt:
            return self._handle_crash(client, reader, "operation interrupted")
        except Exception as exc:
            return self._handle_crash(client, reader, str(exc))

    def _handle_protocol_or_crash(
        self,
        client: WorkerClient,
        reader: LogStreamReader | None,
        result: WorkerResult,
    ) -> OperationResult:
        """Route a failed WorkerResult to crash recovery or RPC error."""
        if result.response is None or not client.is_alive():
            error = result.error or "protocol failure"
            return self._handle_crash(client, reader, error)

        self._graceful_shutdown(client)
        if reader is not None:
            reader.join(timeout=2.0)
            reader.stop()

        log_state = reader.state if reader else None
        return OperationResult(
            success=False,
            rpc_result=result.response,
            exit_code=client.process.returncode if client.process else None,
            error=result.error,
            archive_error=log_state.error if log_state else None,
            log_state=log_state,
        )

    def _graceful_shutdown(self, client: WorkerClient) -> bool:
        """Send rpc.shutdown and wait for graceful EOF + zero exit."""
        try:
            client.send_request("rpc.shutdown", {}, request_id=0)
        except WorkerProcessError:
            client.terminate()
            return False

        proc = client.process
        if proc is None:
            return True

        try:
            proc.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            client.terminate()
            return False

        return proc.returncode == 0

    def _handle_crash(
        self,
        client: WorkerClient,
        reader: LogStreamReader | None,
        error: str,
    ) -> OperationResult:
        """Crash recovery: terminate, drain, repair, return failure."""
        exit_code: int | None = None
        signal_number: int | None = None
        repaired: list[str] = []
        log_state: LogStreamState | None = None
        active_step: str | None = None

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
            archive_error=log_state.error if log_state else None,
            log_state=log_state,
        )
