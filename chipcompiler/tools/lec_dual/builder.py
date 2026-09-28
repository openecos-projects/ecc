#!/usr/bin/env python
from pathlib import Path

from chipcompiler.data import (
    AnalysisPaths,
    ChecklistState,
    LecDualStep,
    LECEngineEnum,
    LecInput,
    LogPaths,
    OutputPaths,
    SubflowState,
    Workspace,
)
from chipcompiler.tools.lec_dual.engines import lec_engine_module
from chipcompiler.tools.lec_result import build_lec_step_space, derive_golden_path, optional_path


def build_engine_steps(workspace: Workspace, step: LecDualStep) -> dict:
    """Fresh per-engine step objects over the aggregate's shared inputs.

    The gate/golden paths come from the aggregate step's already-resolved
    inputs, so each engine consumes exactly what the ledger step consumed.
    """
    return {
        engine.value: lec_engine_module(engine).build_step(
            workspace=workspace,
            step_name=step.name,
            input_def=None,
            input_verilog=step.input.gate_verilog,
            input_db=step.input.golden_verilog,
        )
        for engine in LECEngineEnum.DUAL.spawn_engines
    }


def build_step(
    workspace: Workspace,
    step_name: str,
    input_def: Path | None,
    input_verilog: Path | None,
    input_db: Path | str | None = None,
    output_def: Path | None = None,
    output_verilog: Path | None = None,
    output_gds: Path | None = None,
) -> LecDualStep:
    """The aggregate step plus both engine step objects, in memory only.

    Path-only: no directories or configs are written here;
    build_step_space/build_step_config own the filesystem side effects.
    """
    directory = Path(workspace.directory) / f"{step_name}_dual"
    output_dir = directory / "output"
    gate_verilog = optional_path(input_verilog)
    golden_verilog = optional_path(input_db) or derive_golden_path(gate_verilog)

    step = LecDualStep(
        name=step_name,
        tool="lec_dual",
        version="0.1",
        directory=directory,
        input=LecInput(
            gate_verilog=gate_verilog,
            golden_verilog=golden_verilog,
            db=optional_path(input_db),
        ),
        output=OutputPaths(
            dir=output_dir,
            json=output_dir / f"{workspace.design.name}_{step_name}_result.json",
        ),
        log=LogPaths(
            dir=directory / "log",
            file=directory / "log" / f"{step_name}.log",
        ),
        analysis=AnalysisPaths(dir=directory / "analysis"),
        subflow=SubflowState(path=directory / "subflow.json", steps=[]),
        checklist=ChecklistState(path=directory / "checklist.json", checklist=[]),
    )
    step.engine_steps.update(build_engine_steps(workspace, step))
    return step


def build_step_space(step: LecDualStep) -> None:
    build_lec_step_space(step)
    for engine in LECEngineEnum.DUAL.spawn_engines:
        engine_step = step.engine_steps.get(engine.value)
        if engine_step is not None:
            lec_engine_module(engine).build_step_space(engine_step)


def build_step_config(workspace: Workspace, step: LecDualStep) -> None:
    """Write both engine configs and the aggregate subflow.

    Idempotent across the create-then-run double call: every write is
    deterministic in the step inputs.
    """
    for engine in LECEngineEnum.DUAL.spawn_engines:
        engine_step = step.engine_steps.get(engine.value)
        if engine_step is not None:
            lec_engine_module(engine).build_step_config(workspace, engine_step)

    from chipcompiler.tools.lec_dual.subflow import LecDualSubFlow

    LecDualSubFlow(workspace=workspace, workspace_step=step).build_sub_flow()
