"""Resumed and ranged runs run their analysis waves in parallel.

The selection reaches ``EngineFlow.run_steps(steps=...)`` through
``execute`` and ``rerun``; wave grouping lives in the flow only.
"""

import threading
from types import SimpleNamespace
from typing import Any

import pytest

import chipcompiler.engine.flow as engine_flow
from chipcompiler.data import EccOutput, EccStep, StateEnum, Workspace
from chipcompiler.data.workspace import Flow
from chipcompiler.data.workspace.flow_data import build_dynamic_flow_data
from chipcompiler.engine import rerun
from chipcompiler.engine.flow import EngineFlow
from chipcompiler.engine.observers import WaveObserver

_NAMES = [
    "filler",
    "lvs",
    "drc",
    "antennaCheck",
    "postRouteLec",
    "RCX",
    "sta",
    "powerAnalysis",
    "emir",
    "Harden",
]
_WAIT = 5.0


class _Sink:
    """The run's event sink: records execution events and can cancel."""

    fatal_observer = True

    def __init__(self):
        self.events: list[tuple] = []
        self.cancelled = threading.Event()

    def on_execution_started(self, intent, step_ids):
        self.events.append(("started", intent, step_ids))

    def on_execution_finished(self, state, error):
        self.events.append(("finished", state))

    def on_step_started(self, step):
        pass

    def on_step_completed(self, step, state, error=None):
        pass

    def raise_if_cancelled(self):
        if self.cancelled.is_set():
            raise RuntimeError("run cancelled at a step boundary")


class _Run:
    """Fake ``run_step`` that records what a step saw when it started."""

    def __init__(self, flow: Any, outputs: dict[str, Any]):
        self.flow = flow
        self.outputs = outputs
        self._lock = threading.Lock()
        self.log: list[tuple[str, str]] = []
        self.states: dict[str, StateEnum] = {}
        self.barriers: dict[str, threading.Barrier] = {}
        self.observers: dict[str, Any] = {}
        self.at_start: dict[str, dict] = {}
        self.before_complete: dict[str, Any] = {}
        self.after_barrier: dict[str, Any] = {}
        self.active = 0
        self.peak = 0

    def group(self, names: list[str]) -> None:
        """Hold these steps until all of them run at once."""
        barrier = threading.Barrier(len(names), timeout=_WAIT)
        self.barriers.update({name: barrier for name in names})

    def __call__(self, step, *, rerun=False, observer: Any):
        name = step.name
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.log.append(("start", name))
            self.observers[name] = observer
            self.at_start[name] = {
                "own_output_reset": not (self.outputs[name] / "stale").exists()
                and self.outputs[name].is_dir(),
                "stale_outputs": sorted(
                    other for other, path in self.outputs.items() if (path / "stale").exists()
                ),
            }
        if name in self.barriers:
            self.barriers[name].wait()
        state = self.states.get(name, StateEnum.Success)
        observer.on_step_started(step)
        if name in self.before_complete:
            self.before_complete[name]()
        observer.on_step_completed(step, state)
        if name in self.after_barrier:
            self.after_barrier[name]()
        with self._lock:
            self.active -= 1
            self.log.append(("end", name))
        return state


def _resumed_workspace(tmp_path, monkeypatch, flow_class=EngineFlow):
    """A workspace whose first failed step is ``drc``: filler/lvs done, the rest unrun."""
    home = tmp_path / "home"
    home.mkdir()
    workspace = Workspace(directory=tmp_path, flow=Flow(path=home / "flow.json"))
    flow: Any = flow_class(workspace)
    flow.workspace.flow.data = build_dynamic_flow_data(
        {"start_step": "filler", "end_step": "Harden", "skip_steps": []}
    )
    for record in flow.workspace.flow.steps():
        record["state"] = "Success" if record["name"] in ("filler", "lvs") else "Unstart"
    flow.workspace.flow.steps()[2]["state"] = "Incomplete"  # drc
    assert flow.save()
    flow.workspace_steps = []
    outputs = {}
    for record in flow.workspace.flow.steps():
        directory = tmp_path / record["directory"]
        output = directory / "output"
        output.mkdir(parents=True)
        (output / "stale").write_text("previous run")
        outputs[record["name"]] = output
        flow.workspace_steps.append(
            EccStep(
                name=record["name"],
                tool=record["tool"],
                directory=directory,
                output=EccOutput(dir=output),
            )
        )
    sections: list[str] = []
    flow.workspace.logger = SimpleNamespace(
        log_section=sections.append, info=lambda *a, **k: None, warning=lambda *a, **k: None
    )
    flushed: list[None] = []
    # Plenty of memory: only max_parallel_steps bounds a wave.
    monkeypatch.setattr(
        engine_flow, "read_memory_status", lambda: SimpleNamespace(available_mb=10**9)
    )
    monkeypatch.setattr(engine_flow, "log_flow", lambda **_kwargs: flushed.append(None))
    run = _Run(flow, outputs)
    monkeypatch.setattr(flow, "run_step", run)
    return SimpleNamespace(flow=flow, run=run, sections=sections, flushed=flushed, sink=_Sink())


@pytest.fixture
def resumed(tmp_path, monkeypatch):
    return _resumed_workspace(tmp_path, monkeypatch)


_RESUMED = ["drc", "antennaCheck", "postRouteLec", "RCX", "sta", "powerAnalysis", "emir", "Harden"]


def test_resume_starting_mid_wave_runs_the_rest_of_it_and_the_next_wave_in_parallel(resumed):
    run = resumed.run
    run.group(["drc", "antennaCheck", "postRouteLec", "RCX"])
    run.group(["sta", "powerAnalysis"])

    result = rerun.run_resume(resumed.flow, event_sink=resumed.sink)

    assert result == rerun.StepRunResult(ok=True, executed=tuple(_RESUMED), failed=None)
    assert run.peak == 4
    # a wave starts only after the one before it ended
    wave_one = {"drc", "antennaCheck", "postRouteLec", "RCX"}
    ends = [i for i, (what, name) in enumerate(run.log) if what == "end" and name in wave_one]
    starts = [i for i, (what, name) in enumerate(run.log) if what == "start" and name == "sta"]
    assert max(ends) < min(starts)
    assert run.log[-4:] == [
        ("start", "emir"),
        ("end", "emir"),
        ("start", "Harden"),
        ("end", "Harden"),
    ]
    assert resumed.sink.events == [("started", "rerun", tuple(_RESUMED)), ("finished", "Success")]


def test_each_step_output_is_reset_right_before_it_runs(resumed):
    resumed.run.group(["drc", "antennaCheck", "postRouteLec", "RCX"])
    resumed.run.group(["sta", "powerAnalysis"])

    assert rerun.run_resume(resumed.flow, event_sink=resumed.sink).ok

    assert {name: seen["own_output_reset"] for name, seen in resumed.run.at_start.items()} == {
        name: True for name in _RESUMED
    }
    # Steps later in the selection keep their old output until their turn.
    assert resumed.run.at_start["emir"]["stale_outputs"] == ["Harden", "filler", "lvs"]
    assert resumed.run.at_start["Harden"]["stale_outputs"] == ["filler", "lvs"]


def test_wave_steps_skip_the_step_sections_and_sequential_steps_keep_them(resumed):
    resumed.run.group(["drc", "antennaCheck", "postRouteLec", "RCX"])
    resumed.run.group(["sta", "powerAnalysis"])

    assert rerun.run_resume(resumed.flow, event_sink=resumed.sink).ok

    assert resumed.sections == [
        "ecc - begin step - emir",
        "ecc - end step - emir",
        "ecc - begin step - Harden",
        "ecc - end step - Harden",
    ]
    # the flow log is refreshed after each sequential step and once per wave
    waves = [["drc", "antennaCheck", "postRouteLec", "RCX"], ["sta", "powerAnalysis"]]
    assert len(resumed.flushed) == len(waves) + len(["emir", "Harden"])


def test_wave_steps_share_one_wave_observer(resumed):
    resumed.run.group(["drc", "antennaCheck", "postRouteLec", "RCX"])
    resumed.run.group(["sta", "powerAnalysis"])

    assert rerun.run_resume(resumed.flow, event_sink=resumed.sink).ok

    observers = resumed.run.observers
    wave = ["drc", "antennaCheck", "postRouteLec", "RCX", "sta", "powerAnalysis"]
    assert [isinstance(observers[name], WaveObserver) for name in _RESUMED] == [
        name in wave for name in _RESUMED
    ]


def test_a_failing_wave_step_stops_the_following_steps(resumed):
    run = resumed.run
    run.group(["drc", "antennaCheck", "postRouteLec", "RCX"])
    run.states["postRouteLec"] = StateEnum.Imcomplete

    result = rerun.run_resume(resumed.flow, event_sink=resumed.sink)

    assert result == rerun.StepRunResult(
        ok=False, executed=("drc", "antennaCheck", "RCX"), failed="postRouteLec"
    )
    assert {name for what, name in run.log if what == "start"} == {
        "drc",
        "antennaCheck",
        "postRouteLec",
        "RCX",
    }
    assert resumed.sink.events == [
        ("started", "rerun", tuple(_RESUMED)),
        ("finished", "Incomplete"),
    ]


def test_the_first_failed_step_in_selection_order_is_reported(resumed):
    run = resumed.run
    run.group(["drc", "antennaCheck", "postRouteLec", "RCX"])
    run.states.update({"drc": StateEnum.Invalid, "RCX": StateEnum.Imcomplete})
    rcx_reported = threading.Event()
    run.after_barrier["RCX"] = rcx_reported.set
    run.before_complete["drc"] = lambda: rcx_reported.wait(_WAIT)

    result = rerun.run_resume(resumed.flow, event_sink=resumed.sink)

    # RCX failed first in time; drc is first in the flow.
    assert result == rerun.StepRunResult(
        ok=False, executed=("antennaCheck", "postRouteLec"), failed="drc"
    )


def test_an_incomplete_advisory_step_does_not_stop_the_run(resumed):
    run = resumed.run
    run.group(["drc", "antennaCheck", "postRouteLec", "RCX"])
    run.group(["sta", "powerAnalysis"])
    run.states["antennaCheck"] = StateEnum.Imcomplete

    result = rerun.run_resume(resumed.flow, event_sink=resumed.sink)

    assert result == rerun.StepRunResult(
        ok=True, executed=tuple(name for name in _RESUMED if name != "antennaCheck"), failed=None
    )
    assert run.log[-2:] == [("start", "Harden"), ("end", "Harden")]


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (
            StateEnum.Invalid,
            rerun.StepRunResult(
                ok=False,
                executed=("drc", "antennaCheck", "postRouteLec", "RCX", "sta", "powerAnalysis"),
                failed="emir",
            ),
        ),
        # emir is advisory: Incomplete does not block Harden.
        (
            StateEnum.Imcomplete,
            rerun.StepRunResult(
                ok=True,
                executed=tuple(name for name in _RESUMED if name != "emir"),
                failed=None,
            ),
        ),
    ],
)
def test_a_sequential_step_after_a_wave_stops_the_run_unless_it_is_advisory(
    resumed, state, expected
):
    resumed.run.states["emir"] = state

    assert rerun.run_resume(resumed.flow, event_sink=resumed.sink) == expected
    assert [name for what, name in resumed.run.log if what == "start"][-1] == (
        "emir" if not expected.ok else "Harden"
    )


def test_a_cap_of_one_runs_the_selection_one_step_at_a_time_in_order(resumed):
    resumed.flow.max_parallel_steps = 1

    result = rerun.run_resume(resumed.flow, event_sink=resumed.sink)

    run = resumed.run
    assert result == rerun.StepRunResult(ok=True, executed=tuple(_RESUMED), failed=None)
    assert run.peak == 1
    assert run.log == [(what, name) for name in _RESUMED for what in ("start", "end")]
    assert all(not isinstance(seen, WaveObserver) for seen in run.observers.values())
    tools = {step.name: step.tool for step in resumed.flow.workspace_steps}
    assert resumed.sections == [
        f"{tools[name]} - {what} step - {name}" for name in _RESUMED for what in ("begin", "end")
    ]


def test_run_from_with_a_range_groups_the_selected_part_of_a_wave(resumed):
    run = resumed.run
    run.group(["antennaCheck", "postRouteLec", "RCX"])

    result = rerun.run_from(resumed.flow, "antennaCheck", through="RCX", event_sink=resumed.sink)

    assert result == rerun.StepRunResult(
        ok=True, executed=("antennaCheck", "postRouteLec", "RCX"), failed=None
    )
    assert run.peak == 3


def test_a_selection_skipping_wave_members_still_runs_the_rest_in_parallel(resumed):
    run = resumed.run
    run.group(["lvs", "RCX"])
    steps = [step for step in resumed.flow.workspace_steps if step.name in ("lvs", "RCX")]

    assert resumed.flow.run_steps(rerun=True, observer=resumed.sink, steps=steps) is True

    assert run.peak == 2


def test_only_runs_the_single_step_sequentially_even_inside_a_wave(resumed):
    result = rerun.run_only(resumed.flow, "drc", event_sink=resumed.sink)

    run = resumed.run
    assert result == rerun.StepRunResult(ok=True, executed=("drc",), failed=None)
    assert run.log == [("start", "drc"), ("end", "drc")]
    assert not isinstance(run.observers["drc"], WaveObserver)
    assert resumed.sections == ["ecc - begin step - drc", "ecc - end step - drc"]
    assert resumed.sink.events == [("started", "rerun", ("drc",)), ("finished", "Success")]
    assert run.at_start["drc"] == {
        "own_output_reset": True,
        "stale_outputs": sorted(set(_NAMES) - {"drc"}),
    }


def test_cancel_during_a_wave_keeps_queued_steps_from_starting(resumed):
    resumed.flow.max_parallel_steps = 2
    run = resumed.run
    run.group(["drc", "antennaCheck"])
    # the user cancels while both workers hold a step, before either finishes
    run.before_complete["drc"] = resumed.sink.cancelled.set
    run.before_complete["antennaCheck"] = resumed.sink.cancelled.set

    with pytest.raises(RuntimeError, match="cancelled"):
        rerun.run_resume(resumed.flow, event_sink=resumed.sink)

    # The two running steps finish; nothing queued behind them starts.
    assert sorted(name for what, name in run.log if what == "start") == ["antennaCheck", "drc"]
    # A queued step's output was never reset.
    assert (run.outputs["postRouteLec"] / "stale").exists()
    assert resumed.sink.events[-1] == ("finished", "interrupted")


def test_cancel_between_waves_keeps_the_next_wave_from_starting(resumed):
    run = resumed.run
    run.group(["drc", "antennaCheck", "postRouteLec", "RCX"])
    run.after_barrier["RCX"] = resumed.sink.cancelled.set

    with pytest.raises(RuntimeError, match="cancelled"):
        rerun.run_resume(resumed.flow, event_sink=resumed.sink)

    assert {name for what, name in run.log if what == "start"} == {
        "drc",
        "antennaCheck",
        "postRouteLec",
        "RCX",
    }
    assert resumed.sink.events[-1] == ("finished", "interrupted")


def test_cancel_is_checked_before_every_sequential_step(resumed):
    resumed.flow.max_parallel_steps = 1
    resumed.run.after_barrier["antennaCheck"] = resumed.sink.cancelled.set

    with pytest.raises(RuntimeError, match="cancelled"):
        rerun.run_resume(resumed.flow, event_sink=resumed.sink)

    assert resumed.run.log == [(what, name) for name in _RESUMED[:2] for what in ("start", "end")]
    assert resumed.sink.events[-1] == ("finished", "interrupted")


def test_the_agent_flow_stays_sequential_on_resumed_runs(tmp_path, monkeypatch):
    from agent.engine import AgentEngineFlow

    agent = _resumed_workspace(tmp_path, monkeypatch, AgentEngineFlow)

    result = rerun.run_resume(agent.flow, event_sink=agent.sink)

    assert result == rerun.StepRunResult(ok=True, executed=tuple(_RESUMED), failed=None)
    assert agent.run.peak == 1
