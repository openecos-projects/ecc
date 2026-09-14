"""Post-route LEC gating for the signoff checklist.

Whether a workspace's checklist and signoff artifacts require the
post-route LEC, and which netlists the requirement compares: ledger
membership first (a workspace created with the step skipped never
requires it), then the golden/gate artifacts on disk.
"""

from pathlib import Path

from chipcompiler.data import SkippableStepEnum, StepEnum, Workspace


def post_route_lec_netlists(workspace: Workspace) -> tuple[Path | None, Path | None]:
    """(golden, gate) netlists the post-route LEC proof compares."""
    design = getattr(getattr(workspace, "design", None), "name", "") or ""
    # Golden precedence mirrors the execution wiring (engine/flow.py): the
    # synthesis output when the flow contains Synthesis, else the declared
    # golden netlist, else the origin RTL.
    golden = getattr(getattr(workspace, "design", None), "origin_verilog", None)
    gate = None
    workspace_dir = Path(workspace.directory) if getattr(workspace, "directory", None) else None
    flow = getattr(workspace, "flow", None)
    if workspace_dir is not None:
        # The canonical chain wires postRouteLec's gate input to the LVS
        # output netlist (the step immediately before it), not the filler one.
        gate = workspace_dir / "lvs_ecc" / "output" / f"{design}_lvs.v.gz"
        if flow is not None and flow.has_step(StepEnum.SYNTHESIS):
            golden = workspace_dir / "Synthesis_yosys" / "output" / f"{design}_Synthesis.v.gz"
        else:
            golden = getattr(workspace.design, "golden_verilog", None) or golden
    return golden, gate


def requires_post_route_lec(workspace: Workspace) -> bool:
    """Whether postRouteLec is a required, checkable step for *workspace*."""
    flow = getattr(workspace, "flow", None)
    if flow is None or not flow.has_step(StepEnum.LVS):
        return False
    # A workspace whose ledger has no postRouteLec (skipped at creation)
    # never requires it, regardless of the artifacts on disk.
    if not flow.has_step(SkippableStepEnum.POST_ROUTE_LEC):
        return False
    golden, gate = post_route_lec_netlists(workspace)
    return bool(golden and Path(golden).is_file() and gate and Path(gate).is_file())
