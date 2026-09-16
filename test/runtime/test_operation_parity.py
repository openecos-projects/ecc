import threading
from types import SimpleNamespace

import pytest

from chipcompiler.data import StateEnum
from chipcompiler.runtime.errors import RuntimeApiError
from chipcompiler.runtime.operations import (
    RuntimeOperationIdempotencyConflict,
    RuntimeOperationManager,
)


def test_terminal_step_uses_the_committed_snapshot_revision_for_failures():
    events = []
    commits = []
    manager = RuntimeOperationManager(events.append)
    step = SimpleNamespace(name="LEC", tool="yosys_lec", log=SimpleNamespace(file=""))

    def runner(observer):
        observer.on_step_completed(step, StateEnum.Imcomplete, "missing output")
        raise RuntimeError("run step LEC failed with state Incomplete")

    started = manager.start(
        workspace_id="workspace-1",
        kind="step",
        origin="gui",
        rerun=False,
        step="LEC",
        idempotency_key="failed-lec-revision",
        workspace_revision=6,
        snapshot_committer=lambda *_args: commits.append(7) or 7,
        runner=runner,
    )

    status = _wait_for_terminal(manager, started["operationId"])
    completed = _wait_for_event(events, "step.completed")

    assert status["workspaceRevision"] == 7
    assert commits == [7]
    assert completed["payload"]["workspaceRevision"] == 7
    assert completed["payload"]["stepCommitId"].endswith(":step:7")


def test_rerun_prepared_adopts_and_publishes_the_reset_revision():
    events = []
    manager = RuntimeOperationManager(events.append)

    def runner(observer):
        observer.on_rerun_prepared(
            affected_steps=["preFloorplan", "place"],
            scope="flow",
            workspace_revision=8,
        )
        return {"rerun": True}

    started = manager.start(
        workspace_id="workspace-1",
        kind="flow",
        origin="gui",
        rerun=True,
        step="",
        idempotency_key="rerun-revision",
        workspace_revision=7,
        runner=runner,
    )

    status = _wait_for_terminal(manager, started["operationId"])
    prepared = _wait_for_event(events, "operation.rerun_prepared")

    assert prepared["payload"]["workspaceRevision"] == 8
    assert status["workspaceRevision"] == 8


def test_reusing_a_command_id_with_different_parameters_conflicts():
    release = threading.Event()
    manager = RuntimeOperationManager()
    first = manager.start(
        workspace_id="workspace-1",
        kind="flow",
        origin="gui",
        rerun=False,
        step="",
        idempotency_key="request-1",
        runner=lambda _observer: release.wait(timeout=1) or {},
    )

    try:
        with pytest.raises(RuntimeOperationIdempotencyConflict):
            manager.start(
                workspace_id="workspace-1",
                kind="flow",
                origin="gui",
                rerun=True,
                step="",
                idempotency_key="request-1",
                runner=lambda _observer: {},
            )
    finally:
        release.set()
        _wait_for_terminal(manager, first["operationId"])


def test_command_fingerprint_includes_command_specific_input():
    release = threading.Event()
    manager = RuntimeOperationManager()
    first = manager.start(
        workspace_id="workspace-1",
        kind="step",
        origin="gui",
        rerun=True,
        step="Place",
        idempotency_key="request-1",
        command_input={"resetDependents": False},
        runner=lambda _observer: release.wait(timeout=1) or {},
    )

    try:
        with pytest.raises(RuntimeOperationIdempotencyConflict):
            manager.start(
                workspace_id="workspace-1",
                kind="step",
                origin="gui",
                rerun=True,
                step="Place",
                idempotency_key="request-1",
                command_input={"resetDependents": True},
                runner=lambda _observer: {},
            )
    finally:
        release.set()
        _wait_for_terminal(manager, first["operationId"])


def test_step_diagnostic_persists_structured_tool_error():
    events = []
    manager = RuntimeOperationManager(events.append)
    step = SimpleNamespace(name="place", tool="dreamplace", log=SimpleNamespace(file="place.log"))

    def runner(observer):
        observer.on_step_diagnostic(
            step,
            {"message": "overflow exceeded", "details": {"overflow": 1.2}},
        )
        return {"rerun": False}

    started = manager.start(
        workspace_id="workspace-1",
        kind="step",
        origin="gui",
        rerun=False,
        step="place",
        idempotency_key="diagnostic",
        runner=runner,
    )

    status = _wait_for_terminal(manager, started["operationId"])

    assert status["error"] == {
        "code": "tool_failed",
        "message": "overflow exceeded",
        "step": "place",
        "tool": "dreamplace",
        "logFile": "place.log",
        "details": {"overflow": 1.2},
        "snapshotRevision": 0,
        "eventRevision": 0,
        "operationRevision": 0,
    }
    diagnostic = next(event for event in events if event["type"] == "step.diagnostic")
    assert diagnostic["payload"]["workspaceRevision"] == status["workspaceRevision"] == 0
    assert diagnostic["payload"]["diagnostic"]["operationRevision"] == 0


def test_terminal_completion_preserves_a_prior_structured_diagnostic():
    manager = RuntimeOperationManager()
    step = SimpleNamespace(name="place", tool="dreamplace", log=SimpleNamespace(file="place.log"))

    def runner(observer):
        observer.on_step_diagnostic(step, {"message": "overflow exceeded", "overflow": 1.2})
        observer.on_step_completed(step, StateEnum.Imcomplete, "tool exited with failure")

    started = manager.start(
        workspace_id="workspace-1",
        kind="step",
        origin="gui",
        rerun=False,
        step="place",
        idempotency_key="diagnostic-terminal",
        runner=runner,
    )

    status = _wait_for_terminal(manager, started["operationId"])

    assert status["error"] == {
        "code": "tool_failed",
        "message": "overflow exceeded",
        "step": "place",
        "tool": "dreamplace",
        "logFile": "place.log",
        "overflow": 1.2,
        "snapshotRevision": 0,
        "eventRevision": 0,
        "operationRevision": 0,
    }


def test_snapshot_commit_failure_keeps_a_stable_operation_error_code():
    manager = RuntimeOperationManager()
    step = SimpleNamespace(name="Synthesis", tool="yosys", log=SimpleNamespace(file=""))

    def fail_commit(*_args):
        raise RuntimeApiError(
            "engineering_snapshot_commit_failed",
            "snapshot write failed",
            {"step": "Synthesis"},
        )

    started = manager.start(
        workspace_id="workspace-1",
        kind="step",
        origin="gui",
        rerun=False,
        step="Synthesis",
        idempotency_key="snapshot-failure",
        snapshot_committer=fail_commit,
        runner=lambda observer: observer.on_step_completed(step, StateEnum.Success),
    )

    status = _wait_for_terminal(manager, started["operationId"])

    assert status["state"] == "failed"
    assert status["error"] == {
        "code": "engineering_snapshot_commit_failed",
        "message": "snapshot write failed",
        "step": "Synthesis",
    }


def test_event_consumer_failure_does_not_rollback_a_durable_step_commit():
    manager = RuntimeOperationManager(
        lambda _event: (_ for _ in ()).throw(RuntimeError("IPC down"))
    )
    step = SimpleNamespace(name="Synthesis", tool="yosys", log=SimpleNamespace(file=""))

    started = manager.start(
        workspace_id="workspace-1",
        kind="step",
        origin="gui",
        rerun=False,
        step="Synthesis",
        idempotency_key="publisher-failure",
        snapshot_committer=lambda *_args: 12,
        runner=lambda observer: observer.on_step_completed(step, StateEnum.Success),
    )

    status = _wait_for_terminal(manager, started["operationId"])

    assert status["state"] == "succeeded"
    assert status["workspaceRevision"] == 12


def _wait_for_event(events: list[dict], event_type: str) -> dict:
    for _ in range(200):
        for event in events:
            if event["type"] == event_type:
                return event
        threading.Event().wait(0.01)
    raise AssertionError(f"event not received: {event_type}")


def _wait_for_terminal(manager: RuntimeOperationManager, operation_id: str) -> dict:
    for _ in range(100):
        status = manager.operation_status(operation_id)
        if status["state"] in {"succeeded", "failed", "cancelled", "interrupted"}:
            return status
        threading.Event().wait(0.01)
    return manager.operation_status(operation_id)
