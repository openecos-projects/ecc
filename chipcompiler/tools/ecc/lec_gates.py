"""Post-route LEC gating for the signoff checklist.

Whether a workspace's checklist and signoff artifacts require the
post-route LEC, and which netlists the requirement compares: ledger
membership first (a workspace created with the step skipped never
requires it), then the golden/gate artifacts on disk.
"""

from pathlib import Path

from chipcompiler.data import (
    ADVISORY_FLOW_STEPS,
    FlowStepCategory,
    SkippableStepEnum,
    StepEnum,
    Workspace,
)
from chipcompiler.data.step import STEP_DIRECTORIES, step_directory_for_tool
from chipcompiler.data.workspace.flow_policy import FlowInputResolver, flow_category, step_name


def latest_pnr_output(workspace: Workspace, suffix: str) -> Path | None:
    """Return the latest PNR output matching *suffix* before checker steps."""
    workspace_dir = Path(workspace.directory) if getattr(workspace, "directory", None) else None
    flow = getattr(workspace, "flow", None)
    if workspace_dir is None or flow is None:
        return None

    candidate = None
    for flow_step in flow.steps():
        if flow_category(flow_step) != FlowStepCategory.PNR:
            continue
        tool = flow_step.get("tool")
        name = flow_step.get("name")
        if not tool or not name or name in ADVISORY_FLOW_STEPS:
            continue
        output_dir = workspace_dir / step_directory_for_tool(name, tool) / "output"
        matches = sorted(output_dir.glob(f"*{suffix}"))
        if matches:
            candidate = matches[-1]
    return candidate


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
        gate = _post_route_gate(workspace)
        if flow is not None and flow.has_step(StepEnum.SYNTHESIS):
            golden = (
                workspace_dir
                / STEP_DIRECTORIES[StepEnum.SYNTHESIS.value]
                / "output"
                / f"{design}_Synthesis.v.gz"
            )
        else:
            golden = getattr(workspace.design, "golden_verilog", None) or golden
    return golden, gate


def _post_route_gate(workspace: Workspace) -> Path | None:
    from chipcompiler.engine.step_chain import build_workspace_step_for_info

    records = workspace.flow.steps()
    resolver = FlowInputResolver(records)
    for index, record in enumerate(records):
        step = build_workspace_step_for_info(workspace, record, resolver.input_source(index))
        if step is None:
            continue
        resolver.record(step)
        if step_name(record) == SkippableStepEnum.POST_ROUTE_LEC.value:
            return getattr(step.input, "gate_verilog", None)
    return None


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
