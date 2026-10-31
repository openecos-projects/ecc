"""Select pre/post-CTS inputs and supply the actual design's IO-cell context."""

from pathlib import Path

from chipcompiler.data import SkippableStepEnum, StepEnum, Workspace, WorkspaceStep
from chipcompiler.data.workspace.sdc import is_generated_sdc
from chipcompiler.data.workspace.timing_constraints import (
    scenario_tcl_path,
    timing_scenarios,
    write_timing_io_context,
)
from chipcompiler.rtl2gds import build_rtl2gds_flow
from chipcompiler.utility import json_read

from .module import ECCToolsModule


def step_tcl_path(
    workspace: Workspace,
    step: WorkspaceStep,
    *,
    corner: str = "TYP",
    rc: str = "TYPICAL",
) -> Path | None:
    """Final STA selects its scenario; all other consumers use TYP/TYPICAL."""
    source = workspace.pdk.sdc
    if not is_generated_sdc(source):
        return source
    scenario = next(
        (item for item in timing_scenarios(workspace) if (item.corner, item.rc) == (corner, rc)),
        None,
    )
    if scenario is None:
        raise ValueError(f"No configured timing scenario for {corner}/{rc}")
    names = [entry[0].value for entry in build_rtl2gds_flow()]
    name = StepEnum.DIFF_SIZING.value if step.name == StepEnum.DIFF_BUFFERING.value else step.name
    post_cts = names.index(name) > names.index(SkippableStepEnum.CTS.value)
    return scenario_tcl_path(workspace.directory, scenario, post_cts=post_cts)


def prepare_timing_context(
    workspace: Workspace, step: WorkspaceStep, ecc_module: ECCToolsModule | None = None
) -> None:
    """Select IO policy from fresh iDB data without regenerating constraint files."""
    if not is_generated_sdc(workspace.pdk.sdc):
        return
    if step.data.dir is None:
        raise ValueError(f"Missing data directory for {step.name} timing context")
    context_path = step.data.dir / "timing_context.json"
    context_path.parent.mkdir(parents=True, exist_ok=True)
    owns_module = ecc_module is None
    if ecc_module is None:
        from .runner import create_db_engine

        ecc_module = create_db_engine(workspace, step)
    if ecc_module is None:
        raise RuntimeError(f"Cannot load {step.name}'s input to classify timing IO cells")
    try:
        if not ecc_module.feature_sammry(json_path=context_path):
            raise RuntimeError(f"Cannot export current iDB IO-cell count for {step.name}")
        has_io_cells = json_read(context_path)["Instances"]["iopads"]["num"] > 0
        write_timing_io_context(workspace, has_io_cells=has_io_cells)
    finally:
        if owns_module:
            ecc_module.close()
