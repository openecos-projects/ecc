from threading import Barrier, Event
from types import SimpleNamespace

import chipcompiler.engine.flow as flow_module
from chipcompiler.data import StateEnum
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


def test_only_sta_depends_on_another_checker():
    flow = _CheckerFlow(lambda _step, **_kwargs: StateEnum.Success)

    dependencies = checker_dependencies(flow, [_step(name) for name in CHECKER_NAMES])

    assert dependencies == {
        "lvs": frozenset(),
        "drc": frozenset(),
        "antennaCheck": frozenset(),
        "postRouteLec": frozenset(),
        "RCX": frozenset(),
        "sta": frozenset({"RCX"}),
        "powerAnalysis": frozenset(),
        "emir": frozenset(),
    }


def test_independent_checkers_start_together_and_sta_waits_for_rcx():
    barrier = Barrier(len(CHECKER_NAMES) - 1)
    rcx_finished = Event()
    started = []

    def run_step(step, **_kwargs):
        started.append(step.name)
        if step.name == "sta":
            assert rcx_finished.is_set()
            return StateEnum.Success
        barrier.wait(timeout=10)
        if step.name == "RCX":
            rcx_finished.set()
        return StateEnum.Success

    flow = _CheckerFlow(run_step)
    steps = [_step(name) for name in CHECKER_NAMES]

    states = run_checker_dag(flow, steps, rerun=False, observer=None, workers=len(steps))

    assert states == [StateEnum.Success] * len(steps)
    assert started[-1] == "sta"


def test_checker_parallelism_uses_every_slot_when_memory_allows(monkeypatch, tmp_path):
    flow = EngineFlow(Workspace(directory=tmp_path))
    steps = [_step(name) for name in CHECKER_NAMES]
    monkeypatch.setattr(flow, "_step_memory_estimate_mb", lambda _step: 4096.0)

    monkeypatch.setattr(flow_module, "_available_memory_mb", lambda: 128 * 1024)
    assert flow._checker_parallelism(steps) == len(steps)

    monkeypatch.setattr(flow_module, "_available_memory_mb", lambda: 12 * 1024)
    assert flow._checker_parallelism(steps) == 2
