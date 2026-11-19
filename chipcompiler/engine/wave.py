"""Run one analysis wave: flow steps that read only what earlier steps produced.

``EngineFlow.run_steps`` runs a flow as a sequence of waves (a step outside
any wave is a wave of one). Up to ``workers`` steps of a wave run at once on
threads; one worker runs them in order on the calling thread. Both share one
failure policy:

* every outcome stays paired with its step, in wave order; a step that never
  started is paired with ``None``;
* a step whose state stops the flow, or that raises, sets the wave's stop flag
  on its own thread before that thread can take another step, so no step
  starts after a blocking failure has happened;
* every started step is waited for, then the first exception in wave order is
  re-raised;
* an interrupt of the waiting thread (Ctrl-C) stops queued steps and calls
  ``interrupt`` so the running steps stop their workers; once every running
  step has ended, the interrupt is re-raised.
"""

import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, wait
from typing import TypeVar

Step = TypeVar("Step")
State = TypeVar("State")


def run_wave(
    steps: Sequence[Step],
    run_step: Callable[[Step], State],
    *,
    workers: int,
    stops_flow: Callable[[Step, State], bool],
    interrupt: Callable[[], None] | None = None,
) -> list[tuple[Step, State | None]]:
    stop = threading.Event()

    def start(step: Step) -> State | None:
        if stop.is_set():
            return None
        try:
            state = run_step(step)
        except BaseException:
            stop.set()
            raise
        if stops_flow(step, state):
            stop.set()
        return state

    if workers <= 1 or len(steps) <= 1:
        return [(step, start(step)) for step in steps]

    workers = min(workers, len(steps))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="wave") as pool:
        futures = []
        try:
            for step in steps:
                futures.append(pool.submit(start, step))
            wait(futures)
        except BaseException:
            stop.set()
            if interrupt is not None:
                interrupt()
            wait(futures)
            raise
    for future in futures:
        if (error := future.exception()) is not None:
            raise error
    return [(step, future.result()) for step, future in zip(steps, futures, strict=True)]
