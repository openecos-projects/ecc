from __future__ import annotations

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
_RENDER_ACK_RETRY_SECONDS = 5.0
_RENDER_ACK_PAUSE_SECONDS = 30.0
_RENDER_ACK_ABORT_SECONDS = 300.0
_TERMINAL_OPERATION_STATES = frozenset({"succeeded", "failed", "cancelled"})


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
    run_session_id: str
    runtime_instance_id: str
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
    awaiting_event: dict[str, Any] | None = None
    awaiting_step_commit_id: str | None = None
    workspace_revision: int = 0
    render_sync_state: str = "idle"
    render_retry_count: int = 0
    render_wait_started_at: float | None = None
    last_render_ack_at: float | None = None
    render_sync_degraded: bool = False
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
        self._runtime_instance_id = uuid4().hex
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
                operation_id=f"operation-{uuid4().hex}",
                run_session_id=uuid4().hex,
                runtime_instance_id=self._runtime_instance_id,
                workspace_id=workspace_id,
                kind=kind,
                origin=origin,
                rerun=rerun,
                step=step,
                idempotency_key=idempotency_key,
            )
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

    def is_active(self, operation_id: str) -> bool:
        with self._lock:
            operation = self._operations.get(operation_id)
            return operation is not None and operation.state not in _TERMINAL_OPERATION_STATES

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
            operation.render_wait_started_at = None
            operation.last_render_ack_at = time.time()
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
            if operation.state in _TERMINAL_OPERATION_STATES:
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
        observer = RuntimeFlowObserver(self, operation_id)
        try:
            self._publish(started_event)
            try:
                result = runner(observer)
                with self._lock:
                    operation = self._operations[operation_id]
                    if operation.cancel_requested:
                        raise RuntimeOperationCancelled("operation cancelled at a step boundary")
                    operation.state = "succeeded"
                    operation.result = result
                    operation.updated_at = time.time()
                    event = self._new_event_locked(
                        operation,
                        "operation.completed",
                        {"result": result},
                    )
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
                        {"error": operation.error},
                    )
            except Exception as exc:
                with self._lock:
                    operation = self._operations[operation_id]
                    if operation.cancel_requested and operation.error is None:
                        operation.state = "cancelled"
                        operation.error = {"message": str(exc), "code": "cancelled"}
                        event_type = "operation.cancelled"
                    else:
                        operation.state = "failed"
                        operation.error = operation.error or {
                            "message": str(exc),
                            "code": "command_failed",
                        }
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
    ) -> None:
        """Publish the idempotent GUI reset boundary before a rerun starts."""
        with self._lock:
            operation = self._operations[operation_id]
            operation.updated_at = time.time()
            event = self._new_event_locked(
                operation,
                "operation.rerun_prepared",
                {
                    "affectedSteps": affected_steps,
                    "scope": scope,
                    "targetStep": target_step,
                },
            )
        self._publish(event)

    def step_completed(
        self,
        operation_id: str,
        workspace_step: Any,
        state: Any,
        error: str | None = None,
    ) -> None:
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
            if error:
                log_file = str(getattr(getattr(workspace_step, "log", None), "file", "") or "")
                operation.error = {
                    "code": "tool_failed",
                    "message": error,
                    "step": operation.current_step,
                    "tool": operation.current_tool,
                    "logFile": log_file,
                }
                payload["error"] = operation.error
                payload["logFile"] = log_file
            event = self._new_event_locked(operation, "step.completed", payload)
            if state_value == "Success":
                operation.workspace_revision += 1
                step_commit_id = f"{operation.operation_id}:step:{operation.workspace_revision}"
                payload["stepCommitId"] = step_commit_id
                payload["workspaceRevision"] = operation.workspace_revision
                if not operation.render_sync_degraded:
                    operation.awaiting_event_id = event["eventId"]
                    operation.awaiting_event = event
                    operation.awaiting_step_commit_id = step_commit_id
                    operation.render_sync_state = "waiting_for_gui_sync"
                    operation.render_retry_count = 0
                    operation.render_wait_started_at = time.monotonic()
                    operation.state = "waiting_for_gui_sync"
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
        while True:
            degraded_event: dict[str, Any] | None = None
            replay_event: dict[str, Any] | None = None
            pause_event: dict[str, Any] | None = None
            with self._render_gate:
                operation = self._operations[operation_id]
                if operation.cancel_requested:
                    return False
                if not operation.awaiting_event_id:
                    if operation.state in {
                        "waiting_for_gui_sync",
                        "paused_for_gui_recovery",
                    }:
                        operation.state = "running"
                        operation.updated_at = time.time()
                    return True

                started_at = operation.render_wait_started_at or time.monotonic()
                elapsed = time.monotonic() - started_at
                if elapsed >= _RENDER_ACK_ABORT_SECONDS:
                    awaiting_event_id = operation.awaiting_event_id
                    awaiting_step_commit_id = operation.awaiting_step_commit_id
                    operation.awaiting_event_id = None
                    operation.awaiting_event = None
                    operation.awaiting_step_commit_id = None
                    operation.render_sync_state = "gui_sync_degraded"
                    operation.render_sync_degraded = True
                    operation.state = "running"
                    operation.updated_at = time.time()
                    degraded_event = self._new_event_locked(
                        operation,
                        "operation.gui_sync_degraded",
                        {
                            "eventId": awaiting_event_id,
                            "stepCommitId": awaiting_step_commit_id,
                            "workspaceRevision": operation.workspace_revision,
                        },
                    )
                elif (
                    elapsed >= _RENDER_ACK_PAUSE_SECONDS
                    and operation.render_sync_state != "paused_for_gui_recovery"
                ):
                    operation.render_sync_state = "paused_for_gui_recovery"
                    operation.state = "paused_for_gui_recovery"
                    operation.updated_at = time.time()
                    pause_event = self._new_event_locked(
                        operation,
                        "operation.gui_sync_paused",
                        {
                            "eventId": operation.awaiting_event_id,
                            "stepCommitId": operation.awaiting_step_commit_id,
                            "workspaceRevision": operation.workspace_revision,
                        },
                    )

                if degraded_event is None:
                    operation.render_retry_count += 1
                    if operation.awaiting_event is not None:
                        replay_event = {
                            **operation.awaiting_event,
                            "payload": {
                                **operation.awaiting_event["payload"],
                                "replayed": True,
                                "retryCount": operation.render_retry_count,
                            },
                        }
                    self._render_gate.wait(timeout=_RENDER_ACK_RETRY_SECONDS)

            if degraded_event is not None:
                self._publish(degraded_event)
                return True
            if pause_event is not None:
                self._publish(pause_event)
            if replay_event is not None:
                self._publish(replay_event)

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
        }

    def _publish(self, event: dict[str, Any]) -> None:
        publisher = self._publisher
        if publisher is not None:
            publisher(event)


class RuntimeFlowObserver:
    def __init__(self, manager: RuntimeOperationManager, operation_id: str):
        self._manager = manager
        self._operation_id = operation_id

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
    ) -> None:
        self._manager.rerun_prepared(
            self._operation_id,
            affected_steps=affected_steps,
            scope=scope,
            target_step=target_step,
        )

    def on_step_completed(
        self,
        workspace_step: Any,
        state: Any,
        error: str | None = None,
    ) -> None:
        self._manager.step_completed(self._operation_id, workspace_step, state, error)

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
