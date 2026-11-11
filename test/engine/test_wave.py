"""One failure policy for an analysis wave, with one worker or several."""

import threading
import time
from typing import Any

import pytest

from chipcompiler.engine.wave import run_wave

_WAIT = 5.0


def _stops(_step, state) -> bool:
    return state == "failed"


class _Steps:
    """Scripted wave steps: each records that it started and returns its state."""

    def __init__(self, **behaviour):
        self._behaviour = behaviour
        self._lock = threading.Lock()
        self.started: list[str] = []

    def __call__(self, step: str) -> Any:
        with self._lock:
            self.started.append(step)
        action = self._behaviour.get(step, "ok")
        return action() if callable(action) else action


def test_outcomes_stay_in_wave_order_whatever_the_completion_order():
    drc_done = threading.Event()

    def lvs():
        assert drc_done.wait(_WAIT)
        return "ok"

    def drc():
        drc_done.set()
        return "late-but-first"

    steps = _Steps(lvs=lvs, drc=drc)

    outcomes = run_wave(["lvs", "drc"], steps, workers=2, stops_flow=_stops)

    assert outcomes == [("lvs", "ok"), ("drc", "late-but-first")]


@pytest.mark.parametrize("workers", [1, 2])
def test_no_step_starts_after_a_blocking_failure(workers):
    drc_started, failed = threading.Event(), threading.Event()

    def lvs():
        # With two workers, drc runs beside the failing step and finishes after it.
        assert workers == 1 or drc_started.wait(_WAIT)
        failed.set()
        return "failed"

    def drc():
        drc_started.set()
        assert failed.wait(_WAIT)
        time.sleep(0.2)
        return "ok"

    steps = _Steps(lvs=lvs, drc=drc)

    outcomes = run_wave(
        ["lvs", "drc", "antennaCheck", "RCX"], steps, workers=workers, stops_flow=_stops
    )

    started = ["lvs", "drc"] if workers == 2 else ["lvs"]
    assert (outcomes, steps.started) == (
        [
            ("lvs", "failed"),
            ("drc", "ok" if workers == 2 else None),
            ("antennaCheck", None),
            ("RCX", None),
        ],
        started,
    )


@pytest.mark.parametrize("workers", [1, 2])
def test_an_exception_stops_the_queue_and_is_raised_after_running_steps_return(workers):
    drc_started, raised, drc_returned = threading.Event(), threading.Event(), threading.Event()

    def lvs():
        assert workers == 1 or drc_started.wait(_WAIT)
        raised.set()
        raise PermissionError("cannot reset lvs/output")

    def drc():
        drc_started.set()
        assert raised.wait(_WAIT)
        time.sleep(0.2)
        drc_returned.set()
        return "ok"

    steps = _Steps(lvs=lvs, drc=drc)

    with pytest.raises(PermissionError, match="lvs/output"):
        run_wave(["lvs", "drc", "antennaCheck"], steps, workers=workers, stops_flow=_stops)

    assert (steps.started, drc_returned.is_set()) == (
        (["lvs", "drc"], True) if workers == 2 else (["lvs"], False)
    )


def test_the_first_exception_in_wave_order_wins():
    drc_raised = threading.Event()

    def lvs():
        assert drc_raised.wait(_WAIT)
        raise RuntimeError("lvs commit failed")

    def drc():
        drc_raised.set()
        raise RuntimeError("drc commit failed")

    with pytest.raises(RuntimeError, match="lvs commit failed"):
        run_wave(["lvs", "drc"], _Steps(lvs=lvs, drc=drc), workers=2, stops_flow=_stops)
