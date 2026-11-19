"""Select pre/post-CTS inputs and supply the actual design's IO-cell context."""

from pathlib import Path

from chipcompiler.data import StepEnum, Workspace, WorkspaceStep
from chipcompiler.data.handshake import input_design_states, load_request
from chipcompiler.data.handshake.files import HandshakeError
from chipcompiler.data.types import DesignState
from chipcompiler.data.workspace.sdc import custom_step_sdc_path, is_generated_sdc
from chipcompiler.data.workspace.timing_constraints import (
    generate_timing_scripts,
    scenario_tcl_path,
    timing_scenarios,
)
from chipcompiler.rtl2gds import rtl2gds_step_names
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
    if source is None:
        return None
    post_cts = _reads_clock_tree(step)
    if not is_generated_sdc(source):
        return custom_step_sdc_path(source, workspace.directory, post_cts=post_cts)
    scenario = next(
        (item for item in timing_scenarios(workspace) if (item.corner, item.rc) == (corner, rc)),
        None,
    )
    if scenario is None:
        raise ValueError(f"No configured timing scenario for {corner}/{rc}")
    return scenario_tcl_path(workspace.directory, scenario, post_cts=post_cts)


def _reads_clock_tree(step: WorkspaceStep) -> bool:
    """Whether the design *step* reads carries a clock tree.

    A design from an upstream step carries the design states its response
    published, so a flow that skips CTS keeps the pre-CTS (ideal clock)
    constraints. A declared design, or a step without a request, stands in
    for the canonical chain before the step.
    """
    if step.directory is not None:
        try:
            request = load_request(Path(step.directory))
        except HandshakeError:
            request = None
        if request is not None and request.design_source is not None:
            return DesignState.CLOCK_TREE in input_design_states(request)
    names = rtl2gds_step_names()
    return names.index(step.name) > names.index(StepEnum.CTS.value)


def prepare_timing_context(
    workspace: Workspace, step: WorkspaceStep, ecc_module: ECCToolsModule | None = None
) -> None:
    """Resolve the generated IO rules from fresh iDB data before timing runs."""
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
        generate_timing_scripts(workspace, has_io_cells=has_io_cells)
    finally:
        if owns_module:
            ecc_module.close()
