"""Observed analysis waves run in parallel, bounded by ``max_parallel_steps``."""

import signal
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

import chipcompiler.engine.flow as engine_flow
from chipcompiler.data import DEFAULT_MAX_PARALLEL_STEPS, StateEnum, Workspace
from chipcompiler.data.workspace.flow_data import build_dynamic_flow_data
from chipcompiler.engine import EngineFlow

_WAVE = ["lvs", "drc", "antennaCheck", "postRouteLec", "RCX"]
_WAIT = 5.0


class _Gate:
    """Holds each wave step until *target* steps are running at once."""

    def __init__(self, target: int):
        self._target = target
        self._lock = threading.Lock()
        self._reached = threading.Event()
        self._active = 0
        self.peak = 0

    def __enter__(self):
        with self._lock:
            self._active += 1
            self.peak = max(self.peak, self._active)
            if self._active >= self._target:
                self._reached.set()
        assert self._reached.wait(_WAIT), f"fewer than {self._target} steps ran at once"

    def __exit__(self, *_exc):
        with self._lock:
            self._active -= 1


class _Observer:
    """Records callbacks, flags overlapping ones and optionally cancels."""

    fatal_observer = True
    execution = {"schema_version": 1, "run_id": "run-1"}

    def __init__(self, *, probe_overlap: bool = False):
        self._probe_overlap = probe_overlap
        self.cancelled = threading.Event()
        self._guard = threading.Lock()
        self._second_entered = threading.Event()
        self._inside = 0
        self.overlapped = False
        self.started: list[str] = []

    def _callback(self):
        with self._guard:
            self._inside += 1
            if self._inside > 1:
                self.overlapped = True
                self._second_entered.set()
        if self._probe_overlap:
            # Give a sibling thread the chance to enter while this one is inside.
            self._second_entered.wait(timeout=0.05)
        with self._guard:
            self._inside -= 1

    def on_step_started(self, step):
        self._callback()
        self.started.append(step.name)

    def on_step_completed(self, step, state, error=None):
        self._callback()

    def raise_if_cancelled(self):
        if self.cancelled.is_set():
            raise RuntimeError("run cancelled at a step boundary")


@pytest.fixture
def wave_flow(tmp_path, monkeypatch) -> EngineFlow:
    flow: Any = EngineFlow(Workspace(directory=tmp_path))
    # A file-backed ledger: its lock is what serializes the wave's callbacks.
    flow.workspace.flow.path = tmp_path / "home" / "flow.json"
    flow.workspace.flow.data = build_dynamic_flow_data(
        {"start_step": "filler", "end_step": "RCX", "skip_steps": []}
    )
    flow.workspace_steps = [
        SimpleNamespace(name=record["name"], tool=record["tool"])
        for record in flow.workspace.flow.steps()
    ]
    # Plenty of memory: only max_parallel_steps bounds the wave.
    monkeypatch.setattr(
        engine_flow, "read_memory_status", lambda: SimpleNamespace(available_mb=10**9)
    )
    monkeypatch.setattr(engine_flow, "log_flow", lambda **_kwargs: None)
    return flow


def _fake_run_step(flow: Any, monkeypatch, *, gate: _Gate | None = None):
    """Replace run_step; wave steps report to the observer like the real one."""
    seen: list[tuple[str, Any]] = []

    def run_step(step, *, rerun=False, observer=None):
        seen.append((step.name, observer))
        if observer is not None:
            observer.on_step_started(step)
        if step.name in _WAVE and gate is not None:
            with gate:
                pass
        if observer is not None:
            observer.on_step_completed(step, StateEnum.Success)
        return StateEnum.Success

    monkeypatch.setattr(flow, "run_step", run_step)
    return seen


def test_observed_wave_runs_in_parallel_up_to_the_default_cap(wave_flow, monkeypatch):
    gate = _Gate(DEFAULT_MAX_PARALLEL_STEPS)
    seen = _fake_run_step(wave_flow, monkeypatch, gate=gate)
    observer = _Observer()

    assert wave_flow.run_steps(observer=observer) is True

    assert gate.peak == DEFAULT_MAX_PARALLEL_STEPS
    assert [name for name, _observer in seen] == ["filler", *_WAVE]
    # Wave steps read the run marker through the proxy unchanged.
    assert {run_observer.execution["run_id"] for _name, run_observer in seen} == {"run-1"}


def test_wave_observer_callbacks_never_overlap(wave_flow, monkeypatch):
    _fake_run_step(wave_flow, monkeypatch, gate=_Gate(2))
    observer = _Observer(probe_overlap=True)

    assert wave_flow.run_steps(observer=observer) is True

    assert observer.overlapped is False
    assert sorted(observer.started) == sorted(["filler", *_WAVE])


@pytest.mark.parametrize("cap", [2, 3])
def test_cap_bounds_the_wave_workers(wave_flow, monkeypatch, cap):
    wave_flow.max_parallel_steps = cap
    gate = _Gate(cap)
    _fake_run_step(wave_flow, monkeypatch, gate=gate)

    assert wave_flow.run_steps(observer=_Observer()) is True

    assert gate.peak == cap


def test_one_step_at_a_time_when_cap_is_one(wave_flow, monkeypatch):
    wave_flow.max_parallel_steps = 1
    gate = _Gate(1)
    seen = _fake_run_step(wave_flow, monkeypatch, gate=gate)
    observer = _Observer()

    assert wave_flow.run_steps(observer=observer) is True

    assert gate.peak == 1
    assert [name for name, _observer in seen] == ["filler", *_WAVE]
    # No proxy for a sequential wave: steps get the caller's observer itself.
    assert all(run_observer is observer for _name, run_observer in seen)


def _polling_run_step(flow: Any, monkeypatch, *, gate: _Gate, cancel):
    """Wave steps that, like a step's worker poll loop, run until cancellation is observed."""
    outcomes: dict[str, str] = {}

    def run_step(step, *, rerun=False, observer: Any = None):
        with gate:  # every worker holds a step
            pass
        if step.name == "lvs":
            cancel(observer)
        deadline = time.monotonic() + _WAIT
        while time.monotonic() < deadline:
            try:
                observer.raise_if_cancelled()
            except RuntimeError as exc:  # a cancel: the worker is stopped, the step Incomplete
                outcomes[step.name] = str(exc)
                return StateEnum.Imcomplete
            except KeyboardInterrupt:  # Ctrl-C: the worker is stopped, the step left Ongoing
                outcomes[step.name] = "KeyboardInterrupt"
                raise
            time.sleep(0.01)
        outcomes[step.name] = "never cancelled"
        return StateEnum.Success

    monkeypatch.setattr(flow, "run_step", run_step)
    return outcomes


def test_cancel_before_a_wave_starts_none_of_its_steps(wave_flow, monkeypatch):
    seen = _fake_run_step(wave_flow, monkeypatch)
    observer = _Observer()
    observer.cancelled.set()

    with pytest.raises(RuntimeError, match="cancelled"):
        wave_flow.run_steps(steps=wave_flow.workspace_steps[1:], observer=observer)

    assert seen == []


def test_cancel_within_a_wave_stops_the_running_steps_and_starts_no_queued_one(
    wave_flow, monkeypatch
):
    # `ecc process cancel` while lvs and drc run: their workers stop and the
    # three queued steps never start.
    wave_flow.max_parallel_steps = 2
    outcomes = _polling_run_step(
        wave_flow, monkeypatch, gate=_Gate(2), cancel=lambda observer: observer.cancelled.set()
    )

    observer = _Observer()
    assert wave_flow.run_steps(steps=wave_flow.workspace_steps[1:], observer=observer) is False

    cancelled = "run cancelled at a step boundary"
    assert outcomes == {"lvs": cancelled, "drc": cancelled}


def test_ctrl_c_interrupts_the_running_steps_before_waiting_for_them(wave_flow, monkeypatch):
    wave_flow.max_parallel_steps = 2
    main_thread = threading.main_thread().ident
    assert main_thread is not None
    outcomes = _polling_run_step(
        wave_flow,
        monkeypatch,
        gate=_Gate(2),
        cancel=lambda _observer: signal.pthread_kill(main_thread, signal.SIGINT),
    )

    with pytest.raises(KeyboardInterrupt):
        wave_flow.run_steps(steps=wave_flow.workspace_steps[1:], observer=_Observer())

    assert outcomes == {"lvs": "KeyboardInterrupt", "drc": "KeyboardInterrupt"}


def test_sequential_steps_are_bracketed_by_log_sections(wave_flow, monkeypatch):
    """A fresh `ecc run` relies on run_steps for the per-step log banners."""
    sections: list[str] = []
    wave_flow.workspace.logger = SimpleNamespace(
        log_section=sections.append, info=lambda *a, **k: None, warning=lambda *a, **k: None
    )
    _fake_run_step(wave_flow, monkeypatch)

    assert wave_flow.run_steps(observer=_Observer()) is True

    filler = wave_flow.workspace_steps[0]
    assert sections[:2] == [
        f"{filler.tool} - begin step - filler",
        f"{filler.tool} - end step - filler",
    ]
