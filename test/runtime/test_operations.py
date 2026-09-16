import json
import threading
from types import SimpleNamespace

from chipcompiler.data import StateEnum
from chipcompiler.engine.flow import EngineFlow
from chipcompiler.runtime.operations import RuntimeOperationManager


def test_successful_step_does_not_wait_for_render_ack_before_completing():
    events = []
    completed = threading.Event()
    manager = RuntimeOperationManager(events.append)
    step = SimpleNamespace(name="Synthesis", tool="yosys", log=SimpleNamespace(file=""))

    def runner(observer):
        observer.on_step_started(step)
        observer.on_step_completed(step, StateEnum.Success)
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

    assert started["state"] in {"queued", "running", "succeeded"}
    assert completed.wait(timeout=1)
    step_completed = next(event for event in events if event["type"] == "step.completed")
    assert step_completed["payload"]["stepCommitId"]
    assert step_completed["payload"]["workspaceRevision"] == 1
    status = manager.operation_status(started["operationId"])
    assert status["state"] == "succeeded"
    assert status["renderSyncState"] == "idle"
    assert status["awaitingEventId"] is None
    assert events[-1]["type"] == "operation.completed"


def test_cancel_stops_before_next_engine_flow_step(monkeypatch):
    events = []
    first_step_running = threading.Event()
    release_first_step = threading.Event()
    manager = RuntimeOperationManager(events.append)
    steps = [
        SimpleNamespace(name=name, tool="mock", log=SimpleNamespace(file=""))
        for name in ("Synthesis", "Floorplan")
    ]
    workspace = SimpleNamespace(
        flow=SimpleNamespace(data={"steps": [{}, {}]}),
        logger=SimpleNamespace(log_section=lambda *_args: None, error=lambda *_args: None),
    )
    flow = EngineFlow(workspace=None)
    flow.workspace = workspace
    flow.workspace_steps = steps
    flow.init_db_engine = lambda: True
    executed = []

    def run_step(step, *, rerun=False, observer=None):
        executed.append(step.name)
        observer.on_step_started(step)
        if step.name == "Synthesis":
            first_step_running.set()
            assert release_first_step.wait(timeout=2)
        observer.on_step_completed(step, StateEnum.Success)
        return StateEnum.Success

    flow.run_step = run_step
    monkeypatch.setattr("chipcompiler.engine.flow.log_flow", lambda **_kwargs: None)
    revisions = []

    def commit_step(*_args):
        revisions.append(len(revisions) + 1)
        return revisions[-1]

    started = manager.start(
        workspace_id="workspace-1",
        kind="flow",
        origin="gui",
        rerun=False,
        step="",
        idempotency_key="cancel-at-step-boundary",
        snapshot_committer=commit_step,
        runner=lambda observer: {"succeeded": flow.run_steps(observer=observer)},
    )
    assert first_step_running.wait(timeout=1)
    cancellation = manager.request_cancel(started["operationId"])
    assert cancellation == {
        "accepted": True,
        "operationId": started["operationId"],
        "state": "cancelling",
    }
    release_first_step.set()

    status = _wait_for_terminal(manager, started["operationId"])

    assert status["state"] == "cancelled"
    assert status["workspaceRevision"] == 1
    assert executed == ["Synthesis"]
    assert revisions == [1]
    event_types = [event["type"] for event in events]
    assert event_types.index("step.completed") < event_types.index("operation.cancelled")


def test_queued_cancel_finishes_without_leaving_active_workspace(monkeypatch):
    class DeferredThread:
        def __init__(self, target, args, **_kwargs):
            self._target = target
            self._args = args

        def start(self):
            return None

    monkeypatch.setattr("chipcompiler.runtime.operations.threading.Thread", DeferredThread)
    manager = RuntimeOperationManager()
    started = manager.start(
        workspace_id="workspace-1",
        kind="flow",
        origin="gui",
        rerun=False,
        step="",
        idempotency_key="queued-cancel",
        runner=lambda _observer: {"ok": True},
    )

    assert manager.request_cancel(started["operationId"])["state"] == "cancelling"
    manager._run(started["operationId"], lambda _observer: {"ok": True}, None)

    assert manager.operation_status(started["operationId"])["state"] == "cancelled"
    assert manager.shutdown_barrier() is None


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


def test_operation_manager_keeps_only_latest_terminal_window():
    manager = RuntimeOperationManager()

    for index in range(257):
        started = manager.start(
            workspace_id="workspace-1",
            kind="step",
            origin="gui",
            rerun=False,
            step="step",
            idempotency_key=f"command-{index}",
            runner=lambda _observer: {"ok": True},
        )
        assert _wait_for_terminal(manager, started["operationId"])["state"] == "succeeded"

    assert len(manager.workspace_snapshot("workspace-1")["operations"]) == 256


def test_operation_ledger_recovers_unfinished_operations_as_interrupted(tmp_path):
    ledger = tmp_path / "runtime-commands.json"
    manager = RuntimeOperationManager()
    manager.load_workspace_ledger("workspace-1", ledger)
    release = threading.Event()
    started = manager.start(
        workspace_id="workspace-1",
        kind="flow",
        origin="gui",
        rerun=False,
        step="",
        idempotency_key="running-command",
        runner=lambda _observer: release.wait(timeout=2),
    )
    for _ in range(100):
        if ledger.exists() and started["operationId"] in ledger.read_text():
            break
        threading.Event().wait(0.01)

    restored = RuntimeOperationManager()
    restored_ids = restored.load_workspace_ledger("workspace-1", ledger)
    assert restored_ids == [started["operationId"]]
    assert restored.operation_status(started["operationId"])["state"] == "interrupted"
    release.set()


def test_read_only_ledger_load_does_not_recover_or_rewrite(tmp_path):
    ledger = tmp_path / "runtime-commands.json"
    ledger.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "workspaceId": "workspace-1",
                "operations": [
                    {
                        "operationId": "operation-running",
                        "runSessionId": "session-running",
                        "runtimeInstanceId": "runtime-old",
                        "workspaceId": "workspace-1",
                        "kind": "flow",
                        "origin": "gui",
                        "state": "running",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    before = ledger.read_bytes()

    manager = RuntimeOperationManager()
    loaded = manager.load_workspace_ledger("workspace-1", ledger, recover=False)

    assert loaded == ["operation-running"]
    assert manager.operation_status("operation-running")["state"] == "running"
    assert not manager.is_active("operation-running")
    assert ledger.read_bytes() == before

    assert manager.load_workspace_ledger("workspace-1", ledger) == ["operation-running"]
    assert manager.operation_status("operation-running")["state"] == "interrupted"


def test_operation_ledger_clears_legacy_render_wait_state(tmp_path):
    ledger = tmp_path / "runtime-commands.json"
    ledger.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "workspaceId": "workspace-1",
                "operations": [
                    {
                        "operationId": "operation-legacy",
                        "runSessionId": "session-legacy",
                        "runtimeInstanceId": "runtime-legacy",
                        "workspaceId": "workspace-1",
                        "kind": "flow",
                        "origin": "gui",
                        "state": "waiting_for_gui_sync",
                        "awaitingEventId": "event-legacy",
                        "awaitingStepCommitId": "commit-legacy",
                        "renderSyncState": "waiting_for_gui_sync",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    manager = RuntimeOperationManager()
    manager.load_workspace_ledger("workspace-1", ledger)

    status = manager.operation_status("operation-legacy")
    assert status["state"] == "interrupted"
    assert status["renderSyncState"] == "idle"
    assert status["awaitingEventId"] is None
    assert status["awaitingStepCommitId"] is None


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
