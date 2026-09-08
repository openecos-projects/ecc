from typing import Any


def build_flow_for_workspace(workspace, *, create_step_workspaces: bool = True):
    import chipcompiler.engine as engine_api

    engine_flow = engine_api.EngineFlow(workspace=workspace)
    if not engine_flow.has_init():
        raise ValueError("Workspace has no committed Flow")

    if create_step_workspaces:
        engine_flow.create_step_workspaces()
    return engine_flow


def workspace_step_from_flow(workspace, name: str):
    previous_step = None
    loader = getattr(workspace.flow, "steps", None)
    steps = loader() if callable(loader) else workspace.flow.data.get("steps", [])
    for flow_step in steps:
        workspace_step = _build_workspace_step_for_info(workspace, flow_step, previous_step)
        if flow_step.get("name") == name:
            return workspace_step
        if workspace_step is not None:
            previous_step = workspace_step
    return None


def _build_workspace_step_for_info(workspace, flow_step: dict, previous_step):
    step_name = flow_step.get("name")
    tool = flow_step.get("tool")
    if not step_name or not tool:
        return None

    if previous_step is None:
        input_def = workspace.design.origin_def
        input_verilog = workspace.design.origin_verilog
        input_db = None
    else:
        input_def = previous_step.output.def_ or ""
        input_verilog = previous_step.output.verilog or ""
        input_db = previous_step.output.db or ""

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
