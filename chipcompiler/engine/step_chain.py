"""Canonical workspace-step input chaining for read-only projections."""


def build_workspace_step_for_info(
    workspace, flow_step: dict, previous_step, *, pnr_step=None, created_steps=None
):
    """Build one step using the persisted chain and its explicit input edge."""
    step_name = flow_step.get("name")
    tool = flow_step.get("tool")
    if not step_name or not tool:
        return None

    created_steps = created_steps or {}
    input_step_name = flow_step.get("input_step") or (flow_step.get("info") or {}).get("input_step")
    if input_step_name:
        input_source = created_steps.get(input_step_name)
    elif step_category(flow_step) == "CHECKER":
        input_source = pnr_step or previous_step
    else:
        input_source = previous_step

    if input_source is None:
        input_def = workspace.design.origin_def
        input_verilog = workspace.design.origin_verilog
        input_db = None
    else:
        input_def = input_source.output.def_ or ""
        input_verilog = input_source.output.verilog or ""
        input_db = input_source.output.db or ""

    builder = load_tool_builder(tool)
    if builder is None or not hasattr(builder, "build_step"):
        return None
    return builder.build_step(
        workspace=workspace,
        step_name=step_name,
        input_def=input_def,
        input_verilog=input_verilog,
        input_db=input_db,
    )


def step_category(flow_step: dict) -> str:
    return str(
        flow_step.get("category") or (flow_step.get("info") or {}).get("category") or "PNR"
    ).upper()


def load_tool_builder(tool: str):
    from chipcompiler.tools.registry import load_builder

    return load_builder(tool)
