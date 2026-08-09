from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_LOG_POLL_INTERVAL_SECONDS = 0.25
_MAX_LOG_CHUNK_BYTES = 16 * 1024
_MAX_FINAL_LOG_BYTES = 64 * 1024


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


@dataclass
class RuntimeOperation:
    operation_id: str
    workspace_id: str
    kind: str
    origin: str
    rerun: bool
    step: str = ""
    idempotency_key: str = ""
    state: str = "queued"
    current_step: str = ""
    current_tool: str = ""
    error: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    sequence: int = 0
    awaiting_event_id: str | None = None
    acked_event_ids: set[str] = field(default_factory=set)
    cancel_requested: bool = False
    interruptibility: str = "deferred"


class RuntimeOperationManager:
    """Owns asynchronous GUI operations and their exactly-once event stream."""

    def __init__(self, publisher: Callable[[dict[str, Any]], None] | None = None):
        self._publisher = publisher
        self._lock = threading.RLock()
        self._render_gate = threading.Condition(self._lock)
        self._operations: dict[str, RuntimeOperation] = {}
        self._active_by_workspace: dict[str, str] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._step_log_tails: dict[str, _StepLogTail] = {}
        self._next_operation_id = 1
        self._workspace_sequences: dict[str, int] = {}

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
    ) -> dict[str, Any]:
        with self._lock:
            if idempotency_key:
                known_id = self._idempotency.get((workspace_id, idempotency_key))
                if known_id is not None:
                    return {
                        **self._operation_payload(self._operations[known_id]),
                        "deduplicated": True,
                    }

            active_id = self._active_by_workspace.get(workspace_id)
            if active_id is not None:
                active = self._operations[active_id]
                raise RuntimeOperationConflict(
                    f"workspace already has an active operation: {active.operation_id}"
                )

            operation = RuntimeOperation(
                operation_id=f"operation-{self._next_operation_id}",
                workspace_id=workspace_id,
                kind=kind,
                origin=origin,
                rerun=rerun,
                step=step,
                idempotency_key=idempotency_key,
            )
            self._next_operation_id += 1
            self._operations[operation.operation_id] = operation
            self._active_by_workspace[workspace_id] = operation.operation_id
            if idempotency_key:
                self._idempotency[(workspace_id, idempotency_key)] = operation.operation_id
            queued_event = self._new_event_locked(operation, "operation.queued", {})

        self._publish(queued_event)
        thread = threading.Thread(
            target=self._run,
            args=(operation.operation_id, runner),
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

    def workspace_snapshot(self, workspace_id: str) -> dict[str, Any]:
        with self._lock:
            operations = [
                self._operation_payload(operation)
                for operation in self._operations.values()
                if operation.workspace_id == workspace_id
            ]
            return {
                "workspaceId": workspace_id,
                "lastEventId": f"{workspace_id}:{self._workspace_sequences.get(workspace_id, 0)}",
                "operations": operations,
            }

    def acknowledge_step_rendered(self, operation_id: str, event_id: str) -> dict[str, Any]:
        with self._render_gate:
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
            operation.acked_event_ids.add(event_id)
            operation.awaiting_event_id = None
            operation.updated_at = time.time()
            self._render_gate.notify_all()
            return {
                "accepted": True,
                "duplicate": False,
                "operationId": operation_id,
                "eventId": event_id,
            }

    def request_cancel(self, operation_id: str) -> dict[str, Any]:
        with self._render_gate:
            operation = self._operations.get(operation_id)
            if operation is None:
                raise KeyError(operation_id)
            if operation.state in {"succeeded", "failed", "cancelled"}:
                return {"accepted": False, "operationId": operation_id, "state": operation.state}
            operation.cancel_requested = True
            operation.updated_at = time.time()
            event = self._new_event_locked(operation, "operation.cancel_requested", {})
            self._render_gate.notify_all()
        self._publish(event)
        return {"accepted": True, "operationId": operation_id, "state": operation.state}

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
    ) -> None:
        with self._lock:
            operation = self._operations[operation_id]
            operation.state = "running"
            operation.updated_at = time.time()
            started_event = self._new_event_locked(operation, "operation.started", {})
        self._publish(started_event)

        observer = RuntimeFlowObserver(self, operation_id)
        try:
            result = runner(observer)
            with self._lock:
                operation = self._operations[operation_id]
                if operation.cancel_requested:
                    raise RuntimeOperationCancelled("operation cancelled at a step boundary")
                operation.state = "succeeded"
                operation.result = result
                operation.updated_at = time.time()
                event = self._new_event_locked(operation, "operation.completed", {"result": result})
        except RuntimeOperationCancelled as exc:
            with self._lock:
                operation = self._operations[operation_id]
                operation.state = "cancelled"
                operation.error = {"message": str(exc), "code": "cancelled"}
                operation.updated_at = time.time()
                event = self._new_event_locked(
                    operation, "operation.cancelled", {"error": operation.error}
                )
        except Exception as exc:
            with self._lock:
                operation = self._operations[operation_id]
                if operation.cancel_requested:
                    operation.state = "cancelled"
                    operation.error = {"message": str(exc), "code": "cancelled"}
                    event_type = "operation.cancelled"
                else:
                    operation.state = "failed"
                    operation.error = {"message": str(exc), "code": "command_failed"}
                    event_type = "operation.failed"
                operation.updated_at = time.time()
                event = self._new_event_locked(operation, event_type, {"error": operation.error})
        self._publish(event)
        self._stop_step_log_tail(operation_id)
        with self._lock:
            self._active_by_workspace.pop(self._operations[operation_id].workspace_id, None)

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

    def step_completed(self, operation_id: str, workspace_step: Any, state: Any) -> None:
        self._stop_step_log_tail(operation_id)
        state_value = str(getattr(state, "value", state))
        final_log = _read_final_log(getattr(workspace_step, "log", None))
        with self._render_gate:
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
            event = self._new_event_locked(operation, "step.completed", payload)
            if state_value == "Success":
                operation.awaiting_event_id = event["eventId"]
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
        with self._render_gate:
            operation = self._operations[operation_id]
            while operation.awaiting_event_id and not operation.cancel_requested:
                self._render_gate.wait(timeout=1.0)
            return not operation.cancel_requested

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
            "eventId": f"{operation.workspace_id}:{sequence}",
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

    @staticmethod
    def _operation_payload(operation: RuntimeOperation) -> dict[str, Any]:
        return {
            "operationId": operation.operation_id,
            "workspaceId": operation.workspace_id,
            "kind": operation.kind,
            "origin": operation.origin,
            "rerun": operation.rerun,
            "step": operation.step,
            "state": operation.state,
            "currentStep": operation.current_step,
            "currentTool": operation.current_tool,
            "error": operation.error,
            "result": operation.result,
            "awaitingEventId": operation.awaiting_event_id,
            "cancelRequested": operation.cancel_requested,
            "interruptibility": operation.interruptibility,
            "safeToStop": bool(operation.awaiting_event_id),
            "shutdownBarrier": operation.state not in {"succeeded", "failed", "cancelled"},
            "createdAt": operation.created_at,
            "updatedAt": operation.updated_at,
        }

    def _publish(self, event: dict[str, Any]) -> None:
        publisher = self._publisher
        if publisher is not None:
            publisher(event)


class RuntimeFlowObserver:
    def __init__(self, manager: RuntimeOperationManager, operation_id: str):
        self._manager = manager
        self._operation_id = operation_id

    def on_step_started(self, workspace_step: Any) -> None:
        self._manager.step_started(self._operation_id, workspace_step)

    def on_step_completed(self, workspace_step: Any, state: Any) -> None:
        self._manager.step_completed(self._operation_id, workspace_step, state)

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
