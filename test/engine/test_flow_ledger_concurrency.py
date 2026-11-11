"""Steps of a parallel analysis wave share one ledger without losing each other's commits."""

import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

import chipcompiler.engine.flow as engine_flow
from chipcompiler.data import StateEnum, Workspace
from chipcompiler.data.workspace import Flow
from chipcompiler.data.workspace.flow_ledger import ledger_lock
from chipcompiler.data.workspace.flow_types import load_flow_document
from chipcompiler.engine import EngineFlow
from chipcompiler.engine.step_execution import StepExecutionResult
from test.flow_fixture import current_flow_document

_RESOURCES = {"attempt_id": "attempt-1", "isolated": True}


def _flow(tmp_path, names) -> EngineFlow:
    home = tmp_path / "home"
    home.mkdir()
    flow = EngineFlow(Workspace(directory=tmp_path, flow=Flow(path=home / "flow.json")))
    flow.workspace.flow.data = current_flow_document(
        [
            {"name": name, "tool": "ecc", "state": "Unstart", "runtime": "", "info": {}}
            for name in names
        ]
    )
    assert flow.save()
    return flow


def _on_disk(flow: EngineFlow) -> list[dict[str, Any]]:
    return [
        dict(record) for record in load_flow_document(flow.workspace.flow.path).get("steps", [])
    ]


def _step(name) -> Any:
    return SimpleNamespace(name=name, tool="ecc", feature=SimpleNamespace(step=None))


def _finished(*_args, **_kwargs):
    return StepExecutionResult(
        error=None,
        elapsed_seconds=0.0,
        peak_memory_mb=1.0,
        runtime="0:0:0",
        resource_observation=dict(_RESOURCES),
    )


def _quiet_completion(monkeypatch, refresh=lambda _workspace, _step: None):
    monkeypatch.setattr(EngineFlow, "check_step_result", lambda _self, workspace_step: True)
    monkeypatch.setattr(engine_flow, "_refresh_qor_report", lambda _workspace, _tag: None)
    monkeypatch.setattr(engine_flow, "_refresh_signoff_checklist", refresh)


def test_a_reload_holds_back_a_concurrent_state_save(tmp_path, monkeypatch):
    flow = _flow(tmp_path, ["RCX"])
    read, resume = threading.Event(), threading.Event()

    def held_load(path):
        document = load_flow_document(path)
        read.set()
        resume.wait()
        return document

    monkeypatch.setattr(engine_flow, "load_flow_document", held_load)
    reload = threading.Thread(target=EngineFlow, args=(flow.workspace,))
    save = threading.Thread(
        target=flow.set_state, kwargs={"name": "RCX", "tool": "ecc", "state": StateEnum.Ongoing}
    )
    try:
        reload.start()
        assert read.wait(timeout=5)
        save.start()
        save.join(timeout=0.5)
        # Saved between the reload's read and its replacement, RCX would fall
        # back to Unstart and fail its terminal transition (CI: test_ics55_gcd).
        assert save.is_alive()
    finally:
        resume.set()
        reload.join()
        save.join()

    (on_disk,) = _on_disk(flow)
    assert ((flow.get_step("RCX", "ecc") or {}).get("state"), on_disk["state"]) == (
        "Ongoing",
        "Ongoing",
    )


def test_resources_land_on_the_record_after_a_reload_during_the_step(tmp_path, monkeypatch):
    flow = _flow(tmp_path, ["drc"])
    _quiet_completion(monkeypatch)

    def reloading_execution(workspace, *_args, **_kwargs):
        EngineFlow(workspace)
        return _finished()

    monkeypatch.setattr(engine_flow, "execute_tool_step", reloading_execution)

    assert flow.run_step(_step("drc")) == StateEnum.Success

    (on_disk,) = _on_disk(flow)
    assert (on_disk["state"], on_disk["resource_observation"]) == ("Success", _RESOURCES)


def test_wave_steps_commit_and_refresh_one_at_a_time(tmp_path, monkeypatch):
    names = ["lvs", "drc"]
    flow = _flow(tmp_path, names)
    finished_together = threading.Barrier(len(names))
    refreshing = threading.Event()
    overlapped = []

    def execution(*_args, **_kwargs):
        finished_together.wait(timeout=5)
        return _finished()

    def refresh(_workspace, step):
        if refreshing.is_set():
            overlapped.append(step.name)
        refreshing.set()
        time.sleep(0.3)  # room for a sibling to start rendering a stale ledger
        refreshing.clear()

    _quiet_completion(monkeypatch, refresh)
    monkeypatch.setattr(engine_flow, "execute_tool_step", execution)
    monkeypatch.setattr(EngineFlow, "_checker_parallelism", lambda _self, steps: len(steps))
    steps = [_step(name) for name in names]

    outcomes = flow._run_wave(steps, rerun=False)

    assert (outcomes, overlapped) == ([(step, StateEnum.Success) for step in steps], [])
    assert [record["state"] for record in _on_disk(flow)] == ["Success", "Success"]


def _held_by_caller(flow: EngineFlow) -> bool:
    """Whether the calling thread holds the ledger lock: another thread cannot take it."""
    taken = threading.Event()

    def take():
        with ledger_lock(flow.workspace.flow):
            taken.set()

    threading.Thread(target=take, daemon=True).start()
    return not taken.wait(timeout=0.2)


def test_the_completion_callback_and_its_rollback_are_one_ledger_transaction(tmp_path, monkeypatch):
    flow = _flow(tmp_path, ["lvs"])
    held = []

    class _FailingCommit:
        fatal_observer = True

        def on_step_completed(self, _step, _state, _error=None):
            held.append(_held_by_caller(flow))
            raise RuntimeError("snapshot commit failed")

    _quiet_completion(monkeypatch)
    monkeypatch.setattr(engine_flow, "execute_tool_step", _finished)

    with pytest.raises(RuntimeError, match="snapshot commit failed"):
        flow.run_step(_step("lvs"), observer=_FailingCommit())

    (on_disk,) = _on_disk(flow)
    assert (held, on_disk["state"]) == ([True], "Ongoing")


class _LedgerReader:
    """A run observer that reads the ledger from its callbacks."""

    fatal_observer = True

    def __init__(self, flow: EngineFlow):
        self.flow = flow
        self.lvs_committing = threading.Event()
        self.published: list[dict[str, str]] = []
        self.during_lvs_commit: dict[str, str] = {}

    def states(self) -> dict[str, str]:
        steps = {name: self.flow.get_step(name, "ecc") or {} for name in ("lvs", "drc")}
        return {name: step.get("state", "") for name, step in steps.items()}


def test_a_sibling_never_publishes_a_state_that_is_rolled_back(tmp_path, monkeypatch):
    # lvs's snapshot commit fails and rolls lvs back to Ongoing. drc finishes
    # while that commit runs: it must neither persist beside it nor publish
    # the lvs Success that is about to be withdrawn.
    flow = _flow(tmp_path, ["lvs", "drc"])
    observer: Any = _LedgerReader(flow)

    def on_step_completed(step, _state, _error=None):
        if step.name == "lvs":
            observer.lvs_committing.set()
            time.sleep(0.3)  # room for drc to complete beside the commit
            observer.during_lvs_commit = observer.states()
            raise RuntimeError("snapshot commit failed")
        observer.published.append(observer.states())

    observer.on_step_completed = on_step_completed

    drc_running = threading.Event()

    def execution(_workspace, step, *_args, **_kwargs):
        if step.name == "lvs":
            assert drc_running.wait(timeout=5)
        else:
            drc_running.set()
            assert observer.lvs_committing.wait(timeout=5)
        return _finished()

    _quiet_completion(monkeypatch)
    monkeypatch.setattr(engine_flow, "execute_tool_step", execution)
    monkeypatch.setattr(EngineFlow, "_checker_parallelism", lambda _self, steps: len(steps))

    with pytest.raises(RuntimeError, match="snapshot commit failed"):
        flow._run_wave([_step("lvs"), _step("drc")], rerun=False, observer=observer)

    assert (observer.during_lvs_commit, observer.published) == (
        {"lvs": "Success", "drc": "Ongoing"},
        [{"lvs": "Ongoing", "drc": "Success"}],
    )
    assert [record["state"] for record in _on_disk(flow)] == ["Ongoing", "Success"]


def test_a_callback_reading_the_ledger_does_not_block_a_completing_sibling(tmp_path, monkeypatch):
    # lvs completes while drc's start callback is running and reads the ledger
    # under its lock: one lock for both, so neither waits on the other forever.
    flow = _flow(tmp_path, ["lvs", "drc"])
    observer: Any = _LedgerReader(flow)
    drc_starting, lvs_completing = threading.Event(), threading.Event()

    def on_step_started(step):
        if step.name == "drc":
            drc_starting.set()
            lvs_completing.wait(timeout=0.5)
            with ledger_lock(flow.workspace.flow):
                observer.published.append(observer.states())

    def on_step_completed(_step, _state, _error=None):
        observer.published.append(observer.states())

    observer.on_step_started = on_step_started
    observer.on_step_completed = on_step_completed

    def execution(_workspace, step, *_args, **_kwargs):
        if step.name == "lvs":
            assert drc_starting.wait(timeout=5)
        return _finished()

    def refresh(_workspace, step):
        if step.name == "lvs":
            lvs_completing.set()

    _quiet_completion(monkeypatch, refresh)
    monkeypatch.setattr(engine_flow, "execute_tool_step", execution)
    monkeypatch.setattr(EngineFlow, "_checker_parallelism", lambda _self, steps: len(steps))
    steps = [_step("lvs"), _step("drc")]
    outcomes: list = []
    wave = threading.Thread(
        target=lambda: outcomes.append(flow._run_wave(steps, rerun=False, observer=observer)),
        daemon=True,
    )

    wave.start()
    wave.join(timeout=10)

    assert (wave.is_alive(), outcomes) == (False, [[(step, StateEnum.Success) for step in steps]])
