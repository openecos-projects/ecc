import threading
from types import SimpleNamespace

from chipcompiler.data import StateEnum
from chipcompiler.runtime import operations
from chipcompiler.runtime.operations import RuntimeOperationManager


def test_successful_step_waits_for_matching_render_ack_before_completing():
    events = []
    entered_render_gate = threading.Event()
    completed = threading.Event()
    manager = RuntimeOperationManager(events.append)
    step = SimpleNamespace(name="Synthesis", tool="yosys", log=SimpleNamespace(file=""))

    def runner(observer):
        observer.on_step_started(step)
        observer.on_step_completed(step, StateEnum.Success)
        entered_render_gate.set()
        assert observer.wait_for_step_rendered(step, StateEnum.Success)
        completed.set()
        return {"rerun": False}

    started = manager.start(
        workspace_id="workspace-1",
        kind="flow",
        origin="gui",
        rerun=False,
        step="",
        idempotency_key="request-1",
        runner=runner,
    )

    assert started["state"] in {"queued", "running", "waiting_for_gui_sync"}
    assert entered_render_gate.wait(timeout=1)
    assert not completed.wait(timeout=0.05)
    step_completed = next(event for event in events if event["type"] == "step.completed")
    assert step_completed["payload"]["stepCommitId"]
    assert step_completed["payload"]["workspaceRevision"] == 1
    assert not manager.acknowledge_step_rendered(
        started["operationId"],
        step_completed["eventId"],
        "wrong-step-commit",
        step_completed["payload"]["workspaceRevision"],
    )["accepted"]

    assert manager.acknowledge_step_rendered(
        started["operationId"],
        step_completed["eventId"],
        step_completed["payload"]["stepCommitId"],
        step_completed["payload"]["workspaceRevision"],
    ) == {
        "accepted": True,
        "duplicate": False,
        "operationId": started["operationId"],
        "eventId": step_completed["eventId"],
    }
    assert completed.wait(timeout=1)
    assert manager.operation_status(started["operationId"])["state"] == "succeeded"
    assert events[-1]["type"] == "operation.completed"


def test_render_ack_replays_one_commit_then_pauses_before_a_bounded_timeout(monkeypatch):
    monkeypatch.setattr(operations, "_RENDER_ACK_RETRY_SECONDS", 0.01)
    monkeypatch.setattr(operations, "_RENDER_ACK_PAUSE_SECONDS", 0.02)
    monkeypatch.setattr(operations, "_RENDER_ACK_ABORT_SECONDS", 0.5)
    events = []
    entered_render_gate = threading.Event()
    manager = RuntimeOperationManager(events.append)
    step = SimpleNamespace(name="Synthesis", tool="yosys", log=SimpleNamespace(file=""))

    def runner(observer):
        observer.on_step_started(step)
        observer.on_step_completed(step, StateEnum.Success)
        entered_render_gate.set()
        assert observer.wait_for_step_rendered(step, StateEnum.Success)
        return {"rerun": False}

    started = manager.start(
        workspace_id="workspace-1",
        kind="flow",
        origin="gui",
        rerun=False,
        step="",
        idempotency_key="request-replay",
        runner=runner,
    )
    assert entered_render_gate.wait(timeout=1)
    step_completed = _wait_for_event(events, "step.completed")
    paused = _wait_for_event(events, "operation.gui_sync_paused")
    replays = [
        event
        for event in events
        if event["type"] == "step.completed" and event["payload"].get("replayed")
    ]
    assert paused["payload"]["stepCommitId"] == step_completed["payload"]["stepCommitId"]
    assert replays
    assert all(event["eventId"] == step_completed["eventId"] for event in replays)
    assert (
        manager.operation_status(started["operationId"])["renderSyncState"]
        == "paused_for_gui_recovery"
    )

    assert manager.acknowledge_step_rendered(
        started["operationId"],
        step_completed["eventId"],
        step_completed["payload"]["stepCommitId"],
        step_completed["payload"]["workspaceRevision"],
    )["accepted"]
    assert _wait_for_terminal(manager, started["operationId"])["state"] == "succeeded"


def test_ack_and_start_requests_are_idempotent():
    events = []
    release = threading.Event()
    manager = RuntimeOperationManager(events.append)

    def runner(_observer):
        assert release.wait(timeout=1)
        return {"rerun": False}

    first = manager.start(
        workspace_id="workspace-1",
        kind="flow",
        origin="gui",
        rerun=False,
        step="",
        idempotency_key="request-1",
        runner=runner,
    )
    duplicate = manager.start(
        workspace_id="workspace-1",
        kind="flow",
        origin="gui",
        rerun=False,
        step="",
        idempotency_key="request-1",
        runner=runner,
    )

    assert duplicate["operationId"] == first["operationId"]
    assert duplicate["deduplicated"] is True
    assert manager.acknowledge_step_rendered(first["operationId"], "workspace-1:missing") == {
        "accepted": False,
        "duplicate": False,
        "operationId": first["operationId"],
        "eventId": "workspace-1:missing",
    }
    release.set()
    assert _wait_for_terminal(manager, first["operationId"])["state"] == "succeeded"


def test_active_operation_reports_a_shutdown_barrier_and_safe_boundary():
    release = threading.Event()
    manager = RuntimeOperationManager()
    started = manager.start(
        workspace_id="workspace-1",
        kind="flow",
        origin="gui",
        rerun=False,
        step="",
        idempotency_key="request-1",
        runner=lambda _observer: (release.wait(timeout=1), {"rerun": False})[1],
    )

    barrier = manager.shutdown_barrier()
    status = manager.operation_status(started["operationId"])

    assert barrier is not None
    assert barrier["operationId"] == started["operationId"]
    assert barrier["interruptibility"] == "deferred"
    assert status["shutdownBarrier"] is True
    assert status["safeToStop"] is False
    release.set()


def test_cancel_at_render_ack_boundary_releases_the_waiting_flow():
    entered_render_gate = threading.Event()
    manager = RuntimeOperationManager()
    step = SimpleNamespace(name="Synthesis", tool="yosys", log=SimpleNamespace(file=""))

    def runner(observer):
        observer.on_step_started(step)
        observer.on_step_completed(step, StateEnum.Success)
        entered_render_gate.set()
        if not observer.wait_for_step_rendered(step, StateEnum.Success):
            raise RuntimeError("operation cancelled at a render boundary")
        return {"rerun": False}

    started = manager.start(
        workspace_id="workspace-1",
        kind="flow",
        origin="gui",
        rerun=False,
        step="",
        idempotency_key="request-cancel-at-gate",
        runner=runner,
    )
    assert entered_render_gate.wait(timeout=1)

    assert manager.request_cancel(started["operationId"])["accepted"] is True
    assert _wait_for_terminal(manager, started["operationId"])["state"] == "cancelled"


def test_step_log_events_stream_only_new_log_bytes_and_keep_final_tail(tmp_path):
    events = []
    step_started = threading.Event()
    complete_step = threading.Event()
    manager = RuntimeOperationManager(events.append)
    log_file = tmp_path / "Synthesis.log"
    log_file.write_text("previous run\n", encoding="utf-8")
    step = SimpleNamespace(
        name="Synthesis",
        tool="yosys",
        log=SimpleNamespace(file=str(log_file)),
    )

    def runner(observer):
        observer.on_step_started(step)
        step_started.set()
        assert complete_step.wait(timeout=2)
        observer.on_step_completed(step, StateEnum.Success)
        assert observer.wait_for_step_rendered(step, StateEnum.Success)
        return {"rerun": False}

    started = manager.start(
        workspace_id="workspace-1",
        kind="flow",
        origin="gui",
        rerun=False,
        step="",
        idempotency_key="request-log-stream",
        runner=runner,
    )
    assert step_started.wait(timeout=1)
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write("live line one\nlive line two\n")

    step_log = _wait_for_event(events, "step.log")
    assert step_log["payload"]["chunk"] == "live line one\nlive line two\n"
    assert step_log["payload"]["cursor"] == log_file.stat().st_size

    complete_step.set()
    step_complete = _wait_for_event(events, "step.completed")
    assert step_complete["payload"]["finalLog"] == ("previous run\nlive line one\nlive line two\n")
    assert manager.acknowledge_step_rendered(started["operationId"], step_complete["eventId"])[
        "accepted"
    ]
    assert _wait_for_terminal(manager, started["operationId"])["state"] == "succeeded"


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
        if status["state"] in {"succeeded", "failed", "cancelled"}:
            return status
        threading.Event().wait(0.01)
    return manager.operation_status(operation_id)
