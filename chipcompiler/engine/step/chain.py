"""Build workspace steps along the chain the flow policy resolves."""

from pathlib import Path
from typing import Any

from chipcompiler.data import EccOutput, StepEnum
from chipcompiler.data.flow.document import FlowStepEntry
from chipcompiler.data.flow.policy import FlowInputResolver
from chipcompiler.data.step import recorded_step_directory
from chipcompiler.tools.registry import load_builder


def build_workspace_step_for_info(workspace, flow_step: FlowStepEntry, input_source):
    """Build the step for *flow_step*, wiring *input_source* (None = origin)."""
    step_name = flow_step.get("name")
    tool = flow_step.get("tool")
    if not step_name or not tool:
        return None

    if input_source is None:
        input_def = workspace.design.origin_def
        input_verilog = workspace.design.origin_verilog
        input_db = None
    else:
        input_def = input_source.output.def_ or ""
        input_verilog = input_source.output.verilog or ""
        input_db = input_source.output.db or ""

    builder = load_builder(tool)
    if builder is None or not hasattr(builder, "build_step"):
        return None
    return builder.build_step(
        workspace=workspace,
        step_name=step_name,
        input_def=input_def,
        input_verilog=input_verilog,
        input_db=input_db,
        step_directory=Path(workspace.directory) / recorded_step_directory(flow_step),
    )


def apply_info_spef_override(flow_step: FlowStepEntry, workspace_step) -> None:
    """Apply a persisted ``info.spef`` override to an STA step's output."""
    step_info = flow_step.get("info") or {}
    if (
        str(flow_step.get("name", "")) == StepEnum.STA.value
        and step_info.get("spef")
        and isinstance(workspace_step.output, EccOutput)
    ):
        workspace_step.output.spef = [Path(step_info["spef"])]


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
