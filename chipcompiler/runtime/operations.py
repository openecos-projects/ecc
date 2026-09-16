from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

_LOG_POLL_INTERVAL_SECONDS = 0.25
_MAX_LOG_CHUNK_BYTES = 16 * 1024
_MAX_FINAL_LOG_BYTES = 64 * 1024
_TERMINAL_OPERATION_STATES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})
_MAX_TERMINAL_OPERATIONS = 256
_LEDGER_SCHEMA_VERSION = 1
logger = logging.getLogger(__name__)


@dataclass
class _StepLogTail:
    """A bounded worker-side reader for one active step log."""

    operation_id: str
    path: Path
    step: str
    tool: str
    cursor: int
    stopped: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None


class RuntimeOperationConflict(RuntimeError):
    """A workspace already owns a non-terminal runtime operation."""


class RuntimeOperationCancelled(RuntimeError):
    """Cancellation was accepted at a safe step boundary."""


class RuntimeOperationFailed(RuntimeError):
    """A failed operation with an auditable partial result."""

    def __init__(
        self,
        message: str,
        *,
        result: dict[str, Any],
        code: str = "command_failed",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.result = result


class RuntimeOperationIdempotencyConflict(RuntimeError):
    """A command ID was reused with different immutable input."""


@dataclass
class RuntimeOperation:
    operation_id: str
    run_session_id: str
    runtime_instance_id: str
    workspace_id: str
    kind: str
    origin: str
    rerun: bool
    step: str = ""
    idempotency_key: str = ""
    command_fingerprint: str = ""
    state: str = "queued"
    current_step: str = ""
    current_tool: str = ""
    error: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    sequence: int = 0
    awaiting_event_id: str | None = None
    awaiting_event: dict[str, Any] | None = None
    awaiting_step_commit_id: str | None = None
    workspace_revision: int = 0
    render_sync_state: str = "idle"
    render_retry_count: int = 0
    last_render_ack_at: float | None = None
    acked_event_ids: set[str] = field(default_factory=set)
    cancel_requested: bool = False
    interruptibility: str = "deferred"


class RuntimeOperationManager:
    """Owns asynchronous GUI operations and their exactly-once event stream."""

    def __init__(self, publisher: Callable[[dict[str, Any]], None] | None = None):
        self._publisher = publisher
        self._lock = threading.RLock()
        self._operations: dict[str, RuntimeOperation] = {}
        self._active_by_workspace: dict[str, str] = {}
        self._idempotency: dict[tuple[str, str], tuple[str, str]] = {}
        self._step_log_tails: dict[str, _StepLogTail] = {}
        self._runtime_instance_id = uuid4().hex
        self._workspace_sequences: dict[str, int] = {}
        self._ledger_paths: dict[str, Path] = {}
        self._loaded_ledgers: set[Path] = set()

    def set_publisher(self, publisher: Callable[[dict[str, Any]], None] | None) -> None:
        with self._lock:
            self._publisher = publisher

    def start(
        self,
        *,
        workspace_id: str,
        kind: str,
        origin: str,
        rerun: bool,
        step: str,
        idempotency_key: str,
        runner: Callable[[RuntimeFlowObserver], dict[str, Any]],
        workspace_revision: int = 0,
        snapshot_committer: Callable[[Any, Any, str | None], int] | None = None,
        command_input: dict[str, Any] | None = None,
        ledger_path: str | Path | None = None,
        precondition: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        fingerprint = _command_fingerprint(
            kind=kind,
            origin=origin,
            rerun=rerun,
            step=step,
            workspace_revision=workspace_revision,
            command_input=command_input,
        )
        if ledger_path is not None:
            self.load_workspace_ledger(workspace_id, ledger_path)
        with self._lock:
            if idempotency_key:
                known = self._idempotency.get((workspace_id, idempotency_key))
                if known is not None:
                    known_id, known_fingerprint = known
                    if known_fingerprint and known_fingerprint != fingerprint:
                        raise RuntimeOperationIdempotencyConflict(
                            f"command id reused with different input: {idempotency_key}"
                        )
                    return {
                        **self._operation_payload(self._operations[known_id]),
                        "deduplicated": True,
                    }

            if precondition is not None:
                precondition()

            active_id = self._active_by_workspace.get(workspace_id)
            if active_id is not None:
                active = self._operations[active_id]
                raise RuntimeOperationConflict(
                    f"workspace already has an active operation: {active.operation_id}"
                )

            operation = RuntimeOperation(
                operation_id=f"operation-{uuid4().hex}",
                run_session_id=uuid4().hex,
                runtime_instance_id=self._runtime_instance_id,
                workspace_id=workspace_id,
                kind=kind,
                origin=origin,
                rerun=rerun,
                step=step,
                idempotency_key=idempotency_key,
                command_fingerprint=fingerprint,
                workspace_revision=workspace_revision,
            )
            self._operations[operation.operation_id] = operation
            self._active_by_workspace[workspace_id] = operation.operation_id
            if idempotency_key:
                self._idempotency[(workspace_id, idempotency_key)] = (
                    operation.operation_id,
                    fingerprint,
                )
            self._persist_workspace_locked(workspace_id)
            queued_event = self._new_event_locked(operation, "operation.queued", {})

        self._publish(queued_event)
        thread = threading.Thread(
            target=self._run,
            args=(operation.operation_id, runner, snapshot_committer),
            name=f"ecc-runtime-{operation.operation_id}",
            daemon=True,
        )
        thread.start()
        return self.operation_status(operation.operation_id)

    def operation_status(self, operation_id: str) -> dict[str, Any]:
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is None:
                raise KeyError(operation_id)
            return self._operation_payload(operation)

    def is_active(self, operation_id: str) -> bool:
        with self._lock:
            operation = self._operations.get(operation_id)
            return (
                operation is not None
                and operation.state not in _TERMINAL_OPERATION_STATES
                and self._active_by_workspace.get(operation.workspace_id) == operation_id
            )

    def has_active_workspace(self, workspace_id: str) -> bool:
        with self._lock:
            operation_id = self._active_by_workspace.get(workspace_id)
            if operation_id is None:
                return False
            operation = self._operations.get(operation_id)
            return operation is not None and operation.state not in _TERMINAL_OPERATION_STATES

    def load_workspace_ledger(
        self,
        workspace_id: str,
        ledger_path: str | Path,
        *,
        recover: bool = True,
    ) -> list[str]:
        """Load the bounded execution ledger, optionally marking live work interrupted."""
        from chipcompiler.utility import JsonReadError, json_read_strict

        path = Path(ledger_path).expanduser().resolve()
        with self._lock:
            if path in self._loaded_ledgers:
                if recover:
                    return self._recover_loaded_workspace_locked(workspace_id)
                return []
            self._loaded_ledgers.add(path)
            self._ledger_paths[workspace_id] = path
            try:
                payload = json_read_strict(path)
            except (OSError, JsonReadError):
                return []
            entries = payload.get("operations", []) if isinstance(payload, dict) else payload
            if not isinstance(entries, list):
                return []
            restored: list[str] = []
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("workspaceId") != workspace_id:
                    continue
                operation = _operation_from_payload(entry, self._runtime_instance_id)
                if operation is None:
                    continue
                self._operations[operation.operation_id] = operation
                if operation.idempotency_key:
                    self._idempotency[(workspace_id, operation.idempotency_key)] = (
                        operation.operation_id,
                        operation.command_fingerprint,
                    )
                self._workspace_sequences[workspace_id] = max(
                    self._workspace_sequences.get(workspace_id, 0), operation.sequence
                )
                restored.append(operation.operation_id)
            if recover:
                self._recover_loaded_workspace_locked(workspace_id)
            return restored

    def _recover_loaded_workspace_locked(self, workspace_id: str) -> list[str]:
        recovered: list[str] = []
        for operation in self._operations.values():
            if (
                operation.workspace_id != workspace_id
                or operation.state in _TERMINAL_OPERATION_STATES
            ):
                continue
            operation.state = "interrupted"
            operation.error = {
                "code": "interrupted",
                "message": "Runtime process ended before the Operation completed",
            }
            operation.updated_at = time.time()
            operation.awaiting_event_id = None
            operation.awaiting_event = None
            operation.awaiting_step_commit_id = None
            operation.render_sync_state = "idle"
            self._active_by_workspace.pop(workspace_id, None)
            recovered.append(operation.operation_id)
        self._prune_terminal_locked()
        self._persist_workspace_locked(workspace_id)
        return recovered

    def workspace_snapshot(self, workspace_id: str) -> dict[str, Any]:
        with self._lock:
            operations = [
                self._operation_payload(operation)
                for operation in self._operations.values()
                if operation.workspace_id == workspace_id
            ]
            return {
                "workspaceId": workspace_id,
                "runtimeInstanceId": self._runtime_instance_id,
                "lastEventId": (
                    f"{self._runtime_instance_id}:{workspace_id}:"
                    f"{self._workspace_sequences.get(workspace_id, 0)}"
                ),
                "operations": operations,
            }

    def acknowledge_step_rendered(
        self,
        operation_id: str,
        event_id: str,
        step_commit_id: str = "",
        workspace_revision: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is None:
                raise KeyError(operation_id)
            if event_id in operation.acked_event_ids:
                return {
                    "accepted": True,
                    "duplicate": True,
                    "operationId": operation_id,
                    "eventId": event_id,
                }
            if operation.awaiting_event_id != event_id:
                return {
                    "accepted": False,
                    "duplicate": False,
                    "operationId": operation_id,
                    "eventId": event_id,
                }
            if step_commit_id and operation.awaiting_step_commit_id != step_commit_id:
                return {
                    "accepted": False,
                    "duplicate": False,
                    "operationId": operation_id,
                    "eventId": event_id,
                }
            if (
                workspace_revision is not None
                and workspace_revision != operation.workspace_revision
            ):
                return {
                    "accepted": False,
                    "duplicate": False,
                    "operationId": operation_id,
                    "eventId": event_id,
                }
            operation.acked_event_ids.add(event_id)
            operation.awaiting_event_id = None
            operation.awaiting_event = None
            operation.awaiting_step_commit_id = None
            operation.render_sync_state = "idle"
            operation.last_render_ack_at = time.time()
            operation.updated_at = time.time()
            self._persist_workspace_locked(operation.workspace_id)
            return {
                "accepted": True,
                "duplicate": False,
                "operationId": operation_id,
                "eventId": event_id,
            }

    def request_cancel(self, operation_id: str) -> dict[str, Any]:
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is None:
                raise KeyError(operation_id)
            if operation.state in _TERMINAL_OPERATION_STATES:
                return {"accepted": False, "operationId": operation_id, "state": operation.state}
            operation.cancel_requested = True
            operation.state = "cancelling"
            operation.updated_at = time.time()
            self._persist_workspace_locked(operation.workspace_id)
            event = self._new_event_locked(operation, "operation.cancel_requested", {})
        self._publish(event)
        return {"accepted": True, "operationId": operation_id, "state": operation.state}

    def raise_if_cancel_requested(self, operation_id: str) -> None:
        with self._lock:
            operation = self._operations[operation_id]
            if operation.cancel_requested:
                raise RuntimeOperationCancelled("operation cancelled at a step boundary")

    def shutdown_barrier(self) -> dict[str, Any] | None:
        with self._lock:
            for operation_id in self._active_by_workspace.values():
                operation = self._operations[operation_id]
                return {
                    "operationId": operation.operation_id,
                    "workspaceId": operation.workspace_id,
                    "state": operation.state,
                    "step": operation.current_step,
                    "interruptibility": operation.interruptibility,
                    "safeToStop": bool(operation.awaiting_event_id),
                    "cancelRequested": operation.cancel_requested,
                }
        return None

    def _run(
        self,
        operation_id: str,
        runner: Callable[[RuntimeFlowObserver], dict[str, Any]],
        snapshot_committer: Callable[[Any, Any, str | None], int] | None,
    ) -> None:
        with self._lock:
            operation = self._operations[operation_id]
            if operation.cancel_requested:
                operation.state = "cancelled"
                operation.error = {
                    "message": "operation cancelled before execution",
                    "code": "cancelled",
                }
                operation.updated_at = time.time()
                event = self._new_event_locked(
                    operation,
                    "operation.cancelled",
                    {"error": operation.error},
                )
                self._prune_terminal_locked()
                self._persist_workspace_locked(operation.workspace_id)
                self._active_by_workspace.pop(operation.workspace_id, None)
                publish_before_return = True
            else:
                operation.state = "running"
                operation.updated_at = time.time()
                event = self._new_event_locked(operation, "operation.started", {})
                publish_before_return = False
        if publish_before_return:
            self._publish(event)
            return
        observer = RuntimeFlowObserver(self, operation_id, snapshot_committer)
        try:
            self._publish(event)
            try:
                result = runner(observer)
                with self._lock:
                    operation = self._operations[operation_id]
                    operation.result = result
                    if operation.cancel_requested:
                        raise RuntimeOperationCancelled("operation cancelled at a step boundary")
                    operation.state = "succeeded"
                    operation.updated_at = time.time()
                    event = self._new_event_locked(
                        operation,
                        "operation.completed",
                        {"result": result},
                    )
                    self._prune_terminal_locked()
                    self._persist_workspace_locked(operation.workspace_id)
            except RuntimeOperationCancelled as exc:
                with self._lock:
                    operation = self._operations[operation_id]
                    if operation.error is not None:
                        operation.state = "failed"
                        event_type = "operation.failed"
                    else:
                        operation.state = "cancelled"
                        operation.error = {
                            "message": str(exc),
                            "code": "cancelled",
                        }
                        event_type = "operation.cancelled"
                    operation.updated_at = time.time()
                    event = self._new_event_locked(
                        operation,
                        event_type,
                        {
                            "error": operation.error,
                            **(
                                {"result": operation.result} if operation.result is not None else {}
                            ),
                        },
                    )
            except RuntimeOperationFailed as exc:
                with self._lock:
                    operation = self._operations[operation_id]
                    operation.result = exc.result
                    if operation.cancel_requested and operation.error is None:
                        operation.state = "cancelled"
                        operation.error = {"message": str(exc), "code": "cancelled"}
                        event_type = "operation.cancelled"
                    else:
                        operation.state = "failed"
                        operation.error = operation.error or {
                            "message": str(exc),
                            "code": exc.code,
                        }
                        event_type = "operation.failed"
                    operation.updated_at = time.time()
                    event = self._new_event_locked(
                        operation,
                        event_type,
                        {"error": operation.error, "result": operation.result},
                    )
                    self._prune_terminal_locked()
                    self._persist_workspace_locked(operation.workspace_id)
            except Exception as exc:
                with self._lock:
                    operation = self._operations[operation_id]
                    if operation.cancel_requested and operation.error is None:
                        operation.state = "cancelled"
                        operation.error = {"message": str(exc), "code": "cancelled"}
                        event_type = "operation.cancelled"
                    else:
                        operation.state = "failed"
                        operation.error = operation.error or _operation_error_from_exception(exc)
                        event_type = "operation.failed"
                    operation.updated_at = time.time()
                    payload = {"error": operation.error}
                    if operation.error:
                        payload.update(
                            {
                                key: operation.error[key]
                                for key in ("step", "tool", "logFile")
                                if key in operation.error
                            }
                        )
                    event = self._new_event_locked(operation, event_type, payload)
                    self._prune_terminal_locked()
                    self._persist_workspace_locked(operation.workspace_id)
            self._publish(event)
        finally:
            try:
                self._stop_step_log_tail(operation_id)
            finally:
                with self._lock:
                    self._active_by_workspace.pop(
                        self._operations[operation_id].workspace_id,
                        None,
                    )

    def step_started(self, operation_id: str, workspace_step: Any) -> None:
        self._stop_step_log_tail(operation_id)
        with self._lock:
            operation = self._operations[operation_id]
            operation.current_step = str(getattr(workspace_step, "name", ""))
            operation.current_tool = str(getattr(workspace_step, "tool", ""))
            operation.updated_at = time.time()
            event = self._new_event_locked(
                operation,
                "step.started",
                {
                    "step": operation.current_step,
                    "tool": operation.current_tool,
                    "state": "Ongoing",
                },
            )
            log_tail = _step_log_tail_for(
                operation_id,
                getattr(workspace_step, "log", None),
                operation.current_step,
                operation.current_tool,
            )
            if log_tail is not None:
                self._step_log_tails[operation_id] = log_tail
            self._persist_workspace_locked(operation.workspace_id)
        self._publish(event)
        if log_tail is not None:
            thread = threading.Thread(
                target=self._tail_step_log,
                args=(log_tail,),
                name=f"ecc-runtime-log-{operation_id}",
                daemon=True,
            )
            log_tail.thread = thread
            thread.start()

    def rerun_prepared(
        self,
        operation_id: str,
        *,
        affected_steps: list[str],
        scope: str,
        target_step: str = "",
        workspace_revision: int | None = None,
    ) -> None:
        """Publish the idempotent GUI reset boundary before a rerun starts."""
        with self._lock:
            operation = self._operations[operation_id]
            if workspace_revision is not None:
                operation.workspace_revision = workspace_revision
            operation.updated_at = time.time()
            payload = {
                "affectedSteps": affected_steps,
                "scope": scope,
                "targetStep": target_step,
            }
            if workspace_revision is not None:
                payload["workspaceRevision"] = workspace_revision
            event = self._new_event_locked(
                operation,
                "operation.rerun_prepared",
                payload,
            )
            self._persist_workspace_locked(operation.workspace_id)
        self._publish(event)

    def step_completed(
        self,
        operation_id: str,
        workspace_step: Any,
        state: Any,
        error: str | None = None,
        workspace_revision: int | None = None,
    ) -> None:
        self._stop_step_log_tail(operation_id)
        state_value = str(getattr(state, "value", state))
        final_log = _read_final_log(getattr(workspace_step, "log", None))
        with self._lock:
            operation = self._operations[operation_id]
            operation.current_step = str(getattr(workspace_step, "name", ""))
            operation.current_tool = str(getattr(workspace_step, "tool", ""))
            operation.updated_at = time.time()
            payload: dict[str, Any] = {
                "finalLog": final_log,
                "step": operation.current_step,
                "tool": operation.current_tool,
                "state": state_value,
            }
            if error:
                log_file = str(getattr(getattr(workspace_step, "log", None), "file", "") or "")
                operation.error = operation.error or {
                    "code": "tool_failed",
                    "message": error,
                    "step": operation.current_step,
                    "tool": operation.current_tool,
                    "logFile": log_file,
                }
                payload["error"] = operation.error
                payload["logFile"] = str(operation.error.get("logFile", log_file))
            event = self._new_event_locked(operation, "step.completed", payload)
            if workspace_revision is None:
                operation.workspace_revision += 1
            else:
                operation.workspace_revision = workspace_revision
            step_commit_id = f"{operation.operation_id}:step:{operation.workspace_revision}"
            payload["stepCommitId"] = step_commit_id
            payload["workspaceRevision"] = operation.workspace_revision
            self._persist_workspace_locked(operation.workspace_id)
        self._publish(event)

    def step_diagnostic(
        self,
        operation_id: str,
        workspace_step: Any,
        diagnostic: dict[str, Any],
    ) -> None:
        message = str(diagnostic.get("message", "tool failed"))
        log_file = str(getattr(getattr(workspace_step, "log", None), "file", "") or "")
        with self._lock:
            operation = self._operations[operation_id]
            operation.error = {
                "code": "tool_failed",
                "message": message,
                "step": str(getattr(workspace_step, "name", "")),
                "tool": str(getattr(workspace_step, "tool", "")),
                "logFile": log_file,
                **diagnostic,
            }
            operation.updated_at = time.time()
            revision = operation.workspace_revision
            operation.error.update(
                {
                    "snapshotRevision": revision,
                    "eventRevision": revision,
                    "operationRevision": revision,
                }
            )
            event = self._new_event_locked(
                operation,
                "step.diagnostic",
                {
                    "step": str(getattr(workspace_step, "name", "")),
                    "tool": str(getattr(workspace_step, "tool", "")),
                    "diagnostic": operation.error,
                    "snapshotRevision": revision,
                    "eventRevision": revision,
                    "operationRevision": revision,
                    "workspaceRevision": revision,
                },
            )
            self._persist_workspace_locked(operation.workspace_id)
        self._publish(event)

    def subflow_stage(
        self,
        operation_id: str,
        workspace_step: Any,
        subflow_step: dict[str, Any],
    ) -> None:
        """Publish a saved inner-flow state without waiting for a render ACK."""
        with self._lock:
            operation = self._operations[operation_id]
            step = str(getattr(workspace_step, "name", ""))
            tool = str(getattr(workspace_step, "tool", ""))
            event = self._new_event_locked(
                operation,
                "subflow.stage",
                {
                    "peakMemory": subflow_step.get("peak memory (mb)", 0),
                    "runtime": str(subflow_step.get("runtime", "")),
                    "state": str(subflow_step.get("state", "Unstart")),
                    "step": step,
                    "subflowStep": str(subflow_step.get("name", "")),
                    "tool": tool,
                },
            )
            self._persist_workspace_locked(operation.workspace_id)
        self._publish(event)

    def step_skipped(self, operation_id: str, workspace_step: Any) -> None:
        self._stop_step_log_tail(operation_id)
        with self._lock:
            operation = self._operations[operation_id]
            operation.current_step = str(getattr(workspace_step, "name", ""))
            operation.current_tool = str(getattr(workspace_step, "tool", ""))
            operation.updated_at = time.time()
            event = self._new_event_locked(
                operation,
                "step.completed",
                {
                    "step": operation.current_step,
                    "tool": operation.current_tool,
                    "state": "Skipped",
                },
            )
        self._publish(event)

    def wait_for_step_rendered(self, operation_id: str) -> bool:
        with self._lock:
            return not self._operations[operation_id].cancel_requested

    def _tail_step_log(self, log_tail: _StepLogTail) -> None:
        while not log_tail.stopped.is_set():
            self._publish_step_log_delta(log_tail)
            log_tail.stopped.wait(_LOG_POLL_INTERVAL_SECONDS)

    def _publish_step_log_delta(self, log_tail: _StepLogTail) -> None:
        try:
            size = log_tail.path.stat().st_size
            if size < log_tail.cursor:
                # A rerun may truncate or replace a log file. The renderer treats
                # this as a new bounded stream for the same step attempt.
                log_tail.cursor = 0
            if size <= log_tail.cursor:
                return
            with log_tail.path.open("rb") as log_file:
                log_file.seek(log_tail.cursor)
                chunk = log_file.read(_MAX_LOG_CHUNK_BYTES)
        except OSError:
            return

        if not chunk:
            return
        log_tail.cursor += len(chunk)
        text = chunk.decode("utf-8", errors="replace")
        with self._lock:
            if self._step_log_tails.get(log_tail.operation_id) is not log_tail:
                return
            operation = self._operations.get(log_tail.operation_id)
            if operation is None:
                return
            event = self._new_event_locked(
                operation,
                "step.log",
                {
                    "chunk": text,
                    "cursor": log_tail.cursor,
                    "step": log_tail.step,
                    "tool": log_tail.tool,
                },
            )
        self._publish(event)

    def _stop_step_log_tail(self, operation_id: str) -> None:
        with self._lock:
            log_tail = self._step_log_tails.pop(operation_id, None)
        if log_tail is None:
            return
        log_tail.stopped.set()
        if log_tail.thread is not None and log_tail.thread is not threading.current_thread():
            log_tail.thread.join(timeout=_LOG_POLL_INTERVAL_SECONDS + 0.25)

    def _new_event_locked(
        self,
        operation: RuntimeOperation,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        sequence = self._workspace_sequences.get(operation.workspace_id, 0) + 1
        self._workspace_sequences[operation.workspace_id] = sequence
        operation.sequence = sequence
        return {
            "eventId": f"{self._runtime_instance_id}:{operation.operation_id}:{sequence}",
            "runtimeInstanceId": self._runtime_instance_id,
            "runSessionId": operation.run_session_id,
            "sequence": sequence,
            "type": event_type,
            "workspaceId": operation.workspace_id,
            "operationId": operation.operation_id,
            "origin": operation.origin,
            "kind": operation.kind,
            "rerun": operation.rerun,
            "timestamp": time.time(),
            "payload": payload,
        }

    def _prune_terminal_locked(self) -> None:
        terminal = [
            operation
            for operation in self._operations.values()
            if operation.state in _TERMINAL_OPERATION_STATES
        ]
        if len(terminal) <= _MAX_TERMINAL_OPERATIONS:
            return
        terminal.sort(key=lambda operation: (operation.updated_at, operation.operation_id))
        removed = terminal[: len(terminal) - _MAX_TERMINAL_OPERATIONS]
        removed_ids = {operation.operation_id for operation in removed}
        for operation_id in removed_ids:
            self._operations.pop(operation_id, None)
        self._idempotency = {
            key: record for key, record in self._idempotency.items() if record[0] not in removed_ids
        }

    def _persist_workspace_locked(self, workspace_id: str) -> None:
        path = self._ledger_paths.get(workspace_id)
        if path is None:
            return
        from chipcompiler.utility import json_write

        operations = [
            self._operation_payload(operation)
            for operation in self._operations.values()
            if operation.workspace_id == workspace_id
        ]
        json_write(
            path,
            {
                "schemaVersion": _LEDGER_SCHEMA_VERSION,
                "workspaceId": workspace_id,
                "operations": operations,
            },
        )

    @staticmethod
    def _operation_payload(operation: RuntimeOperation) -> dict[str, Any]:
        return {
            "operationId": operation.operation_id,
            "runSessionId": operation.run_session_id,
            "runtimeInstanceId": operation.runtime_instance_id,
            "workspaceId": operation.workspace_id,
            "kind": operation.kind,
            "origin": operation.origin,
            "rerun": operation.rerun,
            "step": operation.step,
            "idempotencyKey": operation.idempotency_key,
            "commandFingerprint": operation.command_fingerprint,
            "state": operation.state,
            "currentStep": operation.current_step,
            "currentTool": operation.current_tool,
            "error": operation.error,
            "result": operation.result,
            "awaitingEventId": operation.awaiting_event_id,
            "awaitingStepCommitId": operation.awaiting_step_commit_id,
            "workspaceRevision": operation.workspace_revision,
            "renderSyncState": operation.render_sync_state,
            "renderRetryCount": operation.render_retry_count,
            "lastRenderAckAt": operation.last_render_ack_at,
            "cancelRequested": operation.cancel_requested,
            "interruptibility": operation.interruptibility,
            "safeToStop": bool(operation.awaiting_event_id),
            "shutdownBarrier": operation.state not in _TERMINAL_OPERATION_STATES,
            "createdAt": operation.created_at,
            "updatedAt": operation.updated_at,
            "sequence": operation.sequence,
        }

    def _publish(self, event: dict[str, Any]) -> None:
        publisher = self._publisher
        if publisher is not None:
            try:
                publisher(event)
            except Exception:
                logger.exception("runtime event consumer failed: %s", event.get("type"))


class RuntimeFlowObserver:
    fatal_observer = True

    def __init__(
        self,
        manager: RuntimeOperationManager,
        operation_id: str,
        snapshot_committer: Callable[[Any, Any, str | None], int] | None = None,
    ):
        self._manager = manager
        self._operation_id = operation_id
        self._snapshot_committer = snapshot_committer
        self._committed_revision: int | None = None

    @property
    def runtime_operation(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "operation_id": self._operation_id,
            "runtime_instance_id": self._manager._runtime_instance_id,
        }

    def on_step_started(self, workspace_step: Any) -> None:
        self._manager.step_started(self._operation_id, workspace_step)

    def on_rerun_prepared(
        self,
        *,
        affected_steps: list[str],
        scope: str,
        target_step: str = "",
        workspace_revision: int | None = None,
    ) -> None:
        self._manager.rerun_prepared(
            self._operation_id,
            affected_steps=affected_steps,
            scope=scope,
            target_step=target_step,
            workspace_revision=workspace_revision,
        )

    def raise_if_cancelled(self) -> None:
        self._manager.raise_if_cancel_requested(self._operation_id)

    def on_step_completed(
        self,
        workspace_step: Any,
        state: Any,
        error: str | None = None,
    ) -> None:
        if self._committed_revision is None and self._snapshot_committer is not None:
            self.commit_step(workspace_step, state, error)
        self._manager.step_completed(
            self._operation_id,
            workspace_step,
            state,
            error,
            self._committed_revision,
        )
        self._committed_revision = None

    def on_step_diagnostic(
        self,
        workspace_step: Any,
        diagnostic: dict[str, Any],
    ) -> None:
        self._manager.step_diagnostic(self._operation_id, workspace_step, diagnostic)

    def commit_step(self, workspace_step: Any, state: Any, error: str | None = None) -> None:
        if self._snapshot_committer is not None:
            self._committed_revision = self._snapshot_committer(workspace_step, state, error)

    def on_subflow_stage(self, workspace_step: Any, subflow_step: dict[str, Any]) -> None:
        self._manager.subflow_stage(self._operation_id, workspace_step, subflow_step)

    def on_step_skipped(self, workspace_step: Any) -> None:
        self._manager.step_skipped(self._operation_id, workspace_step)

    def wait_for_step_rendered(self, _workspace_step: Any, _state: Any) -> bool:
        return self._manager.wait_for_step_rendered(self._operation_id)


def _read_final_log(log: Any) -> str:
    path = getattr(log, "file", None)
    if not path:
        return ""
    try:
        with Path(path).open("rb") as log_file:
            log_file.seek(0, 2)
            size = log_file.tell()
            log_file.seek(max(0, size - _MAX_FINAL_LOG_BYTES))
            return log_file.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _step_log_tail_for(
    operation_id: str,
    log: Any,
    step: str,
    tool: str,
) -> _StepLogTail | None:
    path = getattr(log, "file", None)
    if not path:
        return None
    log_path = Path(path)
    try:
        cursor = log_path.stat().st_size
    except OSError:
        cursor = 0
    return _StepLogTail(
        operation_id=operation_id,
        path=log_path,
        step=step,
        tool=tool,
        cursor=cursor,
    )


def _operation_from_payload(
    payload: dict[str, Any], runtime_instance_id: str
) -> RuntimeOperation | None:
    operation_id = payload.get("operationId")
    run_session_id = payload.get("runSessionId")
    workspace_id = payload.get("workspaceId")
    kind = payload.get("kind")
    origin = payload.get("origin")
    if not all(
        isinstance(value, str) and value
        for value in (operation_id, run_session_id, workspace_id, kind, origin)
    ):
        return None
    return RuntimeOperation(
        operation_id=operation_id,
        run_session_id=run_session_id,
        runtime_instance_id=runtime_instance_id,
        workspace_id=workspace_id,
        kind=kind,
        origin=origin,
        rerun=bool(payload.get("rerun", False)),
        step=str(payload.get("step", "")),
        idempotency_key=str(payload.get("idempotencyKey", "")),
        command_fingerprint=str(payload.get("commandFingerprint", "")),
        state=str(payload.get("state", "interrupted")),
        current_step=str(payload.get("currentStep", "")),
        current_tool=str(payload.get("currentTool", "")),
        error=payload.get("error") if isinstance(payload.get("error"), dict) else None,
        result=payload.get("result") if isinstance(payload.get("result"), dict) else None,
        created_at=_number(payload.get("createdAt")),
        updated_at=_number(payload.get("updatedAt")),
        sequence=int(payload.get("sequence", 0) or 0),
        workspace_revision=int(payload.get("workspaceRevision", 0) or 0),
        render_sync_state=str(payload.get("renderSyncState", "idle")),
        render_retry_count=int(payload.get("renderRetryCount", 0) or 0),
        last_render_ack_at=_optional_number(payload.get("lastRenderAckAt")),
        cancel_requested=bool(payload.get("cancelRequested", False)),
        interruptibility=str(payload.get("interruptibility", "deferred")),
    )


def _number(value: Any) -> float:
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else time.time()
    )


def _command_fingerprint(
    *,
    kind: str,
    origin: str,
    rerun: bool,
    step: str,
    workspace_revision: int,
    command_input: dict[str, Any] | None = None,
) -> str:
    encoded = json.dumps(
        {
            "kind": kind,
            "origin": origin,
            "rerun": rerun,
            "step": step,
            "workspaceRevision": workspace_revision,
            "commandInput": command_input or {},
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _operation_error_from_exception(exc: Exception) -> dict[str, Any]:
    code = getattr(exc, "code", None)
    data = getattr(exc, "data", None)
    error: dict[str, Any] = {
        "message": str(exc),
        "code": code if isinstance(code, str) and code else "command_failed",
    }
    if isinstance(data, dict):
        error.update(data)
    return error


def _optional_number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
