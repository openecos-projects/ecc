import threading
from types import SimpleNamespace

from chipcompiler.data import StateEnum
from chipcompiler.runtime import operations
from chipcompiler.runtime.operations import RuntimeOperationFailed, RuntimeOperationManager


def test_structured_failure_preserves_partial_result() -> None:
    events = []
    manager = RuntimeOperationManager(events.append)
    partial = {"candidateRootRef": ".agent/candidates/candidate-1"}

    def runner(_observer):
        raise RuntimeOperationFailed("candidate Harden failed", result=partial)

    started = manager.start(
        workspace_id="workspace-1",
        kind="candidate_rerun",
        origin="agent",
        rerun=True,
        step="place",
        idempotency_key="failed-candidate",
        runner=runner,
    )

    status = _wait_for_terminal(manager, started["operationId"])
    assert status["state"] == "failed"
    assert status["result"] == partial
    failed = _wait_for_event(events, "operation.failed")
    assert failed["payload"]["result"] == partial


def test_cancelled_operation_preserves_runner_result() -> None:
    entered = threading.Event()
    release = threading.Event()
    manager = RuntimeOperationManager()

    def runner(_observer):
        entered.set()
        assert release.wait(timeout=1)
        return {"candidateRootRef": ".agent/candidates/candidate-1"}

    started = manager.start(
        workspace_id="workspace-1",
        kind="candidate_rerun",
        origin="agent",
        rerun=True,
        step="place",
        idempotency_key="cancelled-candidate",
        runner=runner,
    )
    assert entered.wait(timeout=1)
    assert manager.request_cancel(started["operationId"])["accepted"] is True
    release.set()

    status = _wait_for_terminal(manager, started["operationId"])
    assert status["state"] == "cancelled"
    assert status["result"] == {"candidateRootRef": ".agent/candidates/candidate-1"}


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


def test_subflow_stage_is_emitted_for_the_active_workspace_step():
    events = []
    released = threading.Event()
    manager = RuntimeOperationManager(events.append)
    step = SimpleNamespace(name="Floorplan", tool="ecc", log=SimpleNamespace(file=""))

    def runner(observer):
        observer.on_step_started(step)
        observer.on_subflow_stage(
            step,
            {
                "name": "init floorplan",
                "state": "Ongoing",
                "runtime": "0:0:1",
                "peak memory (mb)": 12.5,
            },
        )
        assert released.wait(timeout=1)
        return {"rerun": False}

    started = manager.start(
        workspace_id="workspace-1",
        kind="step",
        origin="gui",
        rerun=True,
        step="Floorplan",
        idempotency_key="subflow-stage",
        runner=runner,
    )

    event = _wait_for_event(events, "subflow.stage")
    assert event["operationId"] == started["operationId"]
    assert event["payload"] == {
        "peakMemory": 12.5,
        "runtime": "0:0:1",
        "state": "Ongoing",
        "step": "Floorplan",
        "subflowStep": "init floorplan",
        "tool": "ecc",
    }
    released.set()
    assert _wait_for_terminal(manager, started["operationId"])["state"] == "succeeded"


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


def test_event_identity_is_unique_across_sidecar_operation_managers():
    first_events = []
    second_events = []
    first = RuntimeOperationManager(first_events.append)
    second = RuntimeOperationManager(second_events.append)

    first.start(
        workspace_id="workspace-1",
        kind="flow",
        origin="gui",
        rerun=False,
        step="",
        idempotency_key="first",
        runner=lambda _observer: {"rerun": False},
    )
    second.start(
        workspace_id="workspace-1",
        kind="flow",
        origin="gui",
        rerun=True,
        step="",
        idempotency_key="second",
        runner=lambda _observer: {"rerun": True},
    )

    first_queued = _wait_for_event(first_events, "operation.queued")
    second_queued = _wait_for_event(second_events, "operation.queued")
    assert first_queued["sequence"] == second_queued["sequence"] == 1
    assert first_queued["eventId"] != second_queued["eventId"]
    assert first_queued["runtimeInstanceId"] != second_queued["runtimeInstanceId"]
    assert first_queued["operationId"] != second_queued["operationId"]
    assert first_queued["runSessionId"] != second_queued["runSessionId"]


def test_rerun_prepared_event_carries_the_affected_steps_once():
    events = []
    manager = RuntimeOperationManager(events.append)

    def runner(observer):
        observer.on_rerun_prepared(
            scope="step",
            target_step="Floorplan",
            affected_steps=["Floorplan", "route"],
        )
        return {"rerun": True}

    first = manager.start(
        workspace_id="workspace-1",
        kind="step",
        origin="gui",
        rerun=True,
        step="Floorplan",
        idempotency_key="rerun-prepared",
        runner=runner,
    )
    duplicate = manager.start(
        workspace_id="workspace-1",
        kind="step",
        origin="gui",
        rerun=True,
        step="Floorplan",
        idempotency_key="rerun-prepared",
        runner=runner,
    )

    assert duplicate["operationId"] == first["operationId"]
    prepared = _wait_for_event(events, "operation.rerun_prepared")
    assert prepared["payload"] == {
        "affectedSteps": ["Floorplan", "route"],
        "scope": "step",
        "targetStep": "Floorplan",
    }
    assert len([event for event in events if event["type"] == "operation.rerun_prepared"]) == 1


def test_render_ack_timeout_degrades_and_allows_the_flow_to_continue(monkeypatch):
    monkeypatch.setattr(operations, "_RENDER_ACK_RETRY_SECONDS", 0.01)
    monkeypatch.setattr(operations, "_RENDER_ACK_PAUSE_SECONDS", 0.02)
    monkeypatch.setattr(operations, "_RENDER_ACK_ABORT_SECONDS", 0.04)
    events = []
    manager = RuntimeOperationManager(events.append)
    step = SimpleNamespace(name="Synthesis", tool="yosys", log=SimpleNamespace(file=""))

    def runner(observer):
        observer.on_step_started(step)
        observer.on_step_completed(step, StateEnum.Success)
        assert observer.wait_for_step_rendered(step, StateEnum.Success)
        observer.on_step_started(step)
        observer.on_step_completed(step, StateEnum.Success)
        assert observer.wait_for_step_rendered(step, StateEnum.Success)
        return {"rerun": False}

    started = manager.start(
        workspace_id="workspace-1",
        kind="flow",
        origin="gui",
        rerun=False,
        step="",
        idempotency_key="request-degraded-sync",
        runner=runner,
    )

    degraded = _wait_for_event(events, "operation.gui_sync_degraded")
    assert degraded["payload"]["stepCommitId"]
    assert _wait_for_terminal(manager, started["operationId"])["state"] == "succeeded"
    completed_events = [
        event
        for event in events
        if event["type"] == "step.completed" and not event["payload"].get("replayed")
    ]
    assert len(completed_events) == 2
    assert completed_events[1]["payload"]["stepCommitId"]
    assert (
        manager.operation_status(started["operationId"])["renderSyncState"] == "gui_sync_degraded"
    )
    assert not any(event["type"] == "operation.failed" for event in events)


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


def test_step_error_survives_generic_runner_error_and_releases_workspace(tmp_path):
    events = []
    manager = RuntimeOperationManager(events.append)
    log_file = tmp_path / "place.log"
    log_file.write_text("traceback\n", encoding="utf-8")
    step = SimpleNamespace(
        name="place",
        tool="dreamplace",
        log=SimpleNamespace(file=log_file),
    )

    def runner(observer):
        observer.on_step_started(step)
        observer.on_step_completed(step, StateEnum.Imcomplete, "movable utilization is 100.0%")
        raise RuntimeError("run step place failed with state Imcomplete")

    started = manager.start(
        workspace_id="workspace-1",
        kind="step",
        origin="gui",
        rerun=False,
        step="place",
        idempotency_key="failed-place",
        runner=runner,
    )

    status = _wait_for_terminal(manager, started["operationId"])
    assert status["error"] == {
        "code": "tool_failed",
        "message": "movable utilization is 100.0%",
        "step": "place",
        "tool": "dreamplace",
        "logFile": str(log_file),
    }
    assert _wait_for_event(events, "operation.failed")["payload"]["error"] == status["error"]
    second = manager.start(
        workspace_id="workspace-1",
        kind="step",
        origin="gui",
        rerun=True,
        step="place",
        idempotency_key="retry-place",
        runner=lambda _observer: {"state": "Success"},
    )
    assert _wait_for_terminal(manager, second["operationId"])["state"] == "succeeded"


def test_cancel_does_not_replace_a_specific_tool_error(tmp_path):
    manager = RuntimeOperationManager()
    log_file = tmp_path / "place.log"
    step = SimpleNamespace(
        name="place",
        tool="dreamplace",
        log=SimpleNamespace(file=log_file),
    )
    step_failed = threading.Event()
    release_runner = threading.Event()

    def runner(observer):
        observer.on_step_started(step)
        observer.on_step_completed(step, StateEnum.Imcomplete, "utilization is larger than 0.99")
        step_failed.set()
        assert release_runner.wait(timeout=2)
        raise RuntimeError("run step place failed with state Incomplete")

    started = manager.start(
        workspace_id="workspace-1",
        kind="step",
        origin="gui",
        rerun=False,
        step="place",
        idempotency_key="cancelled-failed-place",
        runner=runner,
    )
    assert step_failed.wait(timeout=1)
    assert manager.request_cancel(started["operationId"])["accepted"] is True
    release_runner.set()

    status = _wait_for_terminal(manager, started["operationId"])
    assert status["state"] == "failed"
    assert status["error"] == {
        "code": "tool_failed",
        "message": "utilization is larger than 0.99",
        "step": "place",
        "tool": "dreamplace",
        "logFile": str(log_file),
    }


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
