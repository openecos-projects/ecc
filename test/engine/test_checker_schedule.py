from threading import Barrier, Event
from types import SimpleNamespace
from typing import cast

import chipcompiler.engine.flow as flow_module
from chipcompiler.data import StateEnum, WorkspaceStep
from chipcompiler.data.workspace import Workspace
from chipcompiler.engine.checker_schedule import checker_dependencies, run_checker_dag
from chipcompiler.engine.flow import EngineFlow

CHECKER_NAMES = (
    "lvs",
    "drc",
    "antennaCheck",
    "postRouteLec",
    "RCX",
    "sta",
    "powerAnalysis",
    "emir",
)


def _step(name: str):
    return SimpleNamespace(name=name, tool="ecc")


class _CheckerFlow:
    def __init__(self, run_step):
        self.run_step = run_step

    def get_step(self, _name, _tool):
        return {}


def test_checker_dependencies_follow_artifact_handoffs():
    flow = _CheckerFlow(lambda _step, **_kwargs: StateEnum.Success)

    dependencies = checker_dependencies(flow, [_step(name) for name in CHECKER_NAMES])

    assert dependencies == {
        "lvs": frozenset(),
        "drc": frozenset(),
        "antennaCheck": frozenset(),
        "postRouteLec": frozenset(),
        "RCX": frozenset(),
        "sta": frozenset({"RCX"}),
        "powerAnalysis": frozenset({"RCX"}),
        "emir": frozenset({"powerAnalysis"}),
    }


def test_checker_waves_follow_artifact_dependencies():
    first_wave = {"lvs", "drc", "antennaCheck", "postRouteLec", "RCX"}
    barrier = Barrier(len(first_wave))
    rcx_finished = Event()
    power_finished = Event()
    started = []

    def run_step(step, **_kwargs):
        started.append(step.name)
        if step.name in first_wave:
            barrier.wait(timeout=10)
            if step.name == "RCX":
                rcx_finished.set()
        if step.name in {"sta", "powerAnalysis"}:
            assert rcx_finished.is_set()
            if step.name == "powerAnalysis":
                power_finished.set()
        if step.name == "emir":
            assert power_finished.is_set()
        return StateEnum.Success

    flow = _CheckerFlow(run_step)
    steps = [_step(name) for name in CHECKER_NAMES]

    states = run_checker_dag(flow, steps, rerun=False, observer=None, workers=len(steps))

    assert states == [StateEnum.Success] * len(steps)
    assert started[0:5] == ["lvs", "drc", "antennaCheck", "postRouteLec", "RCX"]
    assert started[5:7] == ["sta", "powerAnalysis"]
    assert started[-1] == "emir"


def test_checker_parallelism_uses_every_slot_when_memory_allows(monkeypatch, tmp_path):
    flow = EngineFlow(Workspace(directory=tmp_path))
    steps = [_step(name) for name in CHECKER_NAMES]
    monkeypatch.setattr(flow, "_step_memory_estimate_mb", lambda _step: 4096.0)

    monkeypatch.setattr(flow_module, "_available_memory_mb", lambda: 128 * 1024)
    assert flow._checker_parallelism(cast(list[WorkspaceStep], steps)) == len(steps)

    monkeypatch.setattr(flow_module, "_available_memory_mb", lambda: 12 * 1024)
    assert flow._checker_parallelism(cast(list[WorkspaceStep], steps)) == 2
