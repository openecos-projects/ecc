#!/usr/bin/env python
import threading
from pathlib import Path

from chipcompiler.data import LecDualStep, LECEngineEnum, StateEnum, Workspace
from chipcompiler.tools.lec_dual.builder import build_engine_steps
from chipcompiler.tools.lec_dual.engines import lec_engine_module
from chipcompiler.tools.lec_dual.subflow import LecDualSubFlow
from chipcompiler.tools.lec_dual.utility import (
    EngineOutcome,
    engine_availability,
    merge_outcomes,
    read_engine_result,
    write_aggregate_result,
)

_SPAWN_ENGINES = LECEngineEnum.DUAL.spawn_engines


class _ObserverIsolatedWorkspace:
    """Delegate hiding the runtime flow observer from child engine threads.

    The observer is shared mutable workspace state owned by the outer step
    execution; per-engine subflow stages surface only on the aggregate
    step's subflow, never as observer events. Reads and writes of every
    other attribute pass through unchanged.
    """

    __slots__ = ("_delegate",)

    def __init__(self, delegate):
        object.__setattr__(self, "_delegate", delegate)

    def __getattr__(self, name):
        if name == "_runtime_flow_observer":
            return None
        return getattr(self._delegate, name)

    def __setattr__(self, name, value):
        setattr(self._delegate, name, value)


def _delete_file(path) -> bool:
    """Unlink one stale evidence file; False when the unlink itself failed."""
    if not path:
        return True
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        return False
    return True


def _clear_stale_evidence(step: LecDualStep, engine_steps: dict) -> list[str]:
    """Delete the aggregate and per-engine results before anything spawns.

    A kill mid-run must leave no readable prior verdict: the aggregate is
    rewritten exactly once after both engines join, so a pre-existing
    aggregate file after a failed run would be stale evidence. Returns the
    paths that could not be deleted — a stale result that survives its
    deletion stays readable, so the caller must not start the run.
    """
    failures = []
    paths = [step.output.json]
    for engine in _SPAWN_ENGINES:
        engine_step = engine_steps[engine.value]
        paths.append(engine_step.output.json)
        paths.append(getattr(engine_step.report, "status", None))
    for path in paths:
        if not _delete_file(path):
            failures.append(str(path))
    return failures


def _run_engine(workspace: Workspace, engine: LECEngineEnum, engine_step, outcome) -> None:
    """Thread target: run one physical engine, capturing its terminal state."""
    try:
        outcome.succeeded = (
            lec_engine_module(engine).run_step(
                workspace=_ObserverIsolatedWorkspace(workspace),
                step=engine_step,
            )
            is True
        )
    except (Exception, SystemExit) as exc:
        outcome.error = str(exc) or type(exc).__name__


def run_step(workspace: Workspace, step: LecDualStep, ecc_module=None) -> bool:
    del ecc_module
    sub_flow = LecDualSubFlow(workspace=workspace, workspace_step=step)

    # The engine step objects are rebuilt at run time; nothing crosses the
    # step's process boundary by attachment.
    engine_steps = build_engine_steps(workspace, step)
    delete_failures = _clear_stale_evidence(step, engine_steps)
    if delete_failures:
        log_path = step.log.file or ""
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text(
            "Error: failed to delete stale LEC evidence: " + "; ".join(delete_failures) + "\n",
            encoding="utf-8",
        )
        for engine in _SPAWN_ENGINES:
            sub_flow.update_step(
                step_name=LecDualSubFlow.stage_name(engine), state=StateEnum.Invalid
            )
        return False

    outcomes: dict[str, EngineOutcome] = {}
    threads = []
    for engine in _SPAWN_ENGINES:
        stage = LecDualSubFlow.stage_name(engine)
        available, reason = engine_availability(engine)
        outcome = EngineOutcome(engine=engine, available=available, reason=reason)
        outcomes[engine.value] = outcome
        if not available:
            # Degraded mode: the sibling still runs; this engine records
            # its unavailability instead of failing the step.
            sub_flow.update_step(step_name=stage, state=StateEnum.Invalid)
            continue
        sub_flow.update_step(step_name=stage, state=StateEnum.Ongoing)
        thread = threading.Thread(
            target=_run_engine,
            args=(workspace, engine, engine_steps[engine.value], outcome),
            name=f"lec_dual-{engine.value}",
            daemon=True,
        )
        threads.append(thread)

    if not threads:
        log_path = step.log.file or ""
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text(
            "Error: no LEC engine is available: "
            + "; ".join(outcome.reason for outcome in outcomes.values())
            + "\n",
            encoding="utf-8",
        )
        return False

    for thread in threads:
        thread.start()
    # Converge-both: an engine failure never terminates the sibling — the
    # sibling's verdict is the cross-check evidence dual exists for.
    for thread in threads:
        thread.join()

    for outcome in outcomes.values():
        if outcome.available:
            outcome.result = read_engine_result(engine_steps[outcome.engine.value].output.json)
        stage = LecDualSubFlow.stage_name(outcome.engine)
        if not outcome.available:
            continue
        state = StateEnum.Success if outcome.status == "proven" else StateEnum.Imcomplete
        sub_flow.update_step(step_name=stage, state=state)

    payload = merge_outcomes(
        [outcomes[engine.value] for engine in _SPAWN_ENGINES],
        golden_verilog=step.input.golden_verilog,
        gate_verilog=step.input.gate_verilog,
    )
    write_aggregate_result(step.output.json, payload)
    # Mirror the single-engine subflow contract: analysis succeeds only
    # with a proven verdict; anything less stays Unstart.
    if payload["status"] == "proven":
        sub_flow.update_step(step_name="analysis", state=StateEnum.Success)
    return payload["status"] == "proven"
