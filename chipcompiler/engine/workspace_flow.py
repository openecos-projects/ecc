from typing import Any


def build_flow_for_workspace(workspace, *, create_step_workspaces: bool = True):
    import chipcompiler.engine as engine_api

    engine_flow = engine_api.EngineFlow(workspace=workspace)
    if not engine_flow.has_init():
        raise ValueError("Workspace has no committed Flow")

    if create_step_workspaces:
        engine_flow.create_step_workspaces()
    return engine_flow


def iter_workspace_steps(workspace):
    """Yield ``(flow_step, workspace_step)`` pairs in ledger order.

    The chain is walked once: each step builds on the previous successfully
    built step. A step whose tool builder cannot be constructed yields
    ``None`` without nulling the steps after it.
    """
    flow = getattr(workspace, "flow", None)
    if flow is None:
        return
    previous_step = None
    pnr_step = None
    created_steps = {}
    for flow_step in flow.steps():
        try:
            workspace_step = _build_workspace_step_for_info(
                workspace,
                flow_step,
                previous_step,
                pnr_step=pnr_step,
                created_steps=created_steps,
            )
        except (ImportError, AttributeError, TypeError, ValueError):
            workspace_step = None
        yield flow_step, workspace_step
        if workspace_step is not None:
            created_steps[workspace_step.name] = workspace_step
            if _step_category(flow_step) == "PNR" and workspace_step.tool not in _lec_step_tools():
                pnr_step = workspace_step
            previous_step = workspace_step


def _build_workspace_step_for_info(
    workspace, flow_step: dict, previous_step, *, pnr_step=None, created_steps=None
):
    step_name = flow_step.get("name")
    tool = flow_step.get("tool")
    if not step_name or not tool:
        return None

    created_steps = created_steps or {}
    input_step_name = flow_step.get("input_step") or (flow_step.get("info") or {}).get("input_step")
    if input_step_name:
        input_source = created_steps.get(input_step_name)
    elif _step_category(flow_step) == "CHECKER":
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

    builder = _load_tool_builder(tool)
    if builder is None or not hasattr(builder, "build_step"):
        return None

    return builder.build_step(
        workspace=workspace,
        step_name=step_name,
        input_def=input_def,
        input_verilog=input_verilog,
        input_db=input_db,
    )


def _step_category(flow_step: dict) -> str:
    return str(
        flow_step.get("category")
        or (flow_step.get("info") or {}).get("category")
        or "PNR"
    ).upper()


def _lec_step_tools() -> frozenset[str]:
    from chipcompiler.data import LEC_STEP_TOOLS

    return LEC_STEP_TOOLS


def _load_tool_builder(tool: str):
    import importlib

    module_alias = {
        "klayout": "klayout_tool",
        "dreamplace": "ecc_dreamplace",
        "sizer": "ecc_sizer",
    }
    module_name = module_alias.get(tool, tool)
    return importlib.import_module(f"chipcompiler.tools.{module_name}.builder")


def init_db_engine_for_workspace_step(engine_flow, workspace_step):
    engine_db = getattr(engine_flow, "engine_db", None)
    if engine_db is None:
        from chipcompiler.engine import EngineDB

        engine_db = EngineDB(workspace=engine_flow.workspace)
        engine_flow.engine_db = engine_db
    elif engine_db.has_init():
        return True

    return engine_db.create_db_engine(step=workspace_step)


def success_state():
    from chipcompiler.data import StateEnum

    return StateEnum.Success


def state_value(state: Any) -> str:
    return getattr(state, "value", str(state))
