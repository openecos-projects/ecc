"""Build one workspace step from the input source the flow policy resolved."""

from pathlib import Path

from chipcompiler.data import EccOutput, StepEnum
from chipcompiler.tools.registry import load_builder


def build_workspace_step_for_info(workspace, flow_step: dict, input_source):
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
    )


def apply_info_spef_override(flow_step: dict, workspace_step) -> None:
    """Apply a persisted ``info.spef`` override to an STA step's output."""
    step_info = flow_step.get("info") or {}
    if (
        str(flow_step.get("name", "")) == StepEnum.STA.value
        and step_info.get("spef")
        and isinstance(workspace_step.output, EccOutput)
    ):
        workspace_step.output.spef = [Path(step_info["spef"])]
