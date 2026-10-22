from typing import Any

from chipcompiler.data.workspace.flow_policy import FlowInputResolver
from chipcompiler.engine.step_chain import build_workspace_step_for_info


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
    records = flow.steps()
    resolver = FlowInputResolver(records)
    for index, flow_step in enumerate(records):
        try:
            workspace_step = build_workspace_step_for_info(
                workspace, flow_step, resolver.input_source(index)
            )
        except (ImportError, AttributeError, TypeError, ValueError):
            workspace_step = None
        yield flow_step, workspace_step
        if workspace_step is not None:
            resolver.record(workspace_step)


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
