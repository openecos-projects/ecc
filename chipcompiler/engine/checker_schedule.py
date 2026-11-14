"""Dependency-aware execution of the post-filler checker steps."""

from concurrent.futures import (
    FIRST_COMPLETED,
    CancelledError,
    Future,
    ThreadPoolExecutor,
    wait,
)
from typing import Any

from chipcompiler.data import ADVISORY_FLOW_STEPS, StateEnum
from chipcompiler.data.types import flow_step_policy
from chipcompiler.data.workspace.flow_policy import explicit_input_step


def checker_dependencies(flow, steps):
    """Return the declared dependencies that must finish before each step.

    The batch is anchored at ``filler``, so checkers without an explicit edge
    start together. Policy edges (``RCX -> STA``, ``RCX -> powerAnalysis``,
    ``powerAnalysis -> emir``) and ledger ``input_step`` edges serialize
    execution.
    """
    names = {step.name for step in steps}
    dependencies = {}
    for step in steps:
        record = flow.get_step(step.name, step.tool) or {}
        required = set(flow_step_policy(step.name).depends_on)
        explicit = explicit_input_step(record)
        if explicit is not None:
            required.add(explicit)
        dependencies[step.name] = frozenset(required & names)
    return dependencies


def run_checker_dag(flow, steps, *, rerun: bool, observer, workers: int) -> list[StateEnum]:
    """Run ready checker steps concurrently while preserving dependencies.

    Failure semantics match the serial flow: no new ready work is scheduled
    after a blocking failure, already-running checkers drain, and work that was
    never started is reported as Unstart. Advisory Incomplete results remain
    non-blocking, as do deliberate Skipped results.
    """
    if not steps:
        return []
    dependencies = checker_dependencies(flow, steps)
    pending = {step.name: step for step in steps}
    states: dict[str, StateEnum] = {}
    active: dict[Future[StateEnum], Any] = {}
    failed = False
    worker_limit = max(1, min(workers, len(steps)))

    with ThreadPoolExecutor(max_workers=worker_limit, thread_name_prefix="checker") as executor:
        while pending or active:
            if not failed:
                ready = [
                    step
                    for step in steps
                    if step.name in pending and dependencies[step.name] <= states.keys()
                ]
                capacity = worker_limit - len(active)
                for step in ready[:capacity]:
                    pending.pop(step.name)
                    future = executor.submit(flow.run_step, step, rerun=rerun, observer=observer)
                    active[future] = step

            if not active:
                break
            done, _ = wait(tuple(active), return_when=FIRST_COMPLETED)
            for future in done:
                step = active.pop(future)
                try:
                    state = future.result()
                except CancelledError:
                    states[step.name] = StateEnum.Unstart
                    continue
                states[step.name] = state
                if not _completed_successfully(step.name, state):
                    failed = True
            if failed:
                for future in tuple(active):
                    if future.cancel():
                        active.pop(future)

    return [states.get(step.name, StateEnum.Unstart) for step in steps]


def _completed_successfully(step_name: str, state: StateEnum) -> bool:
    return state in {StateEnum.Success, StateEnum.Skipped} or (
        step_name in ADVISORY_FLOW_STEPS and state == StateEnum.Imcomplete
    )
