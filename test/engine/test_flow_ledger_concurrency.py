"""Steps of a parallel checker wave share one ledger without losing each other's commits."""

import threading
import time
from types import SimpleNamespace
from typing import Any

import chipcompiler.engine.flow as engine_flow
from chipcompiler.data import StateEnum, Workspace
from chipcompiler.data.workspace import Flow
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

    states = flow._run_checker_batch([_step(name) for name in names], rerun=False)

    assert (states, overlapped) == ([StateEnum.Success, StateEnum.Success], [])
    assert [record["state"] for record in _on_disk(flow)] == ["Success", "Success"]
