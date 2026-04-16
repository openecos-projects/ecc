#!/usr/bin/env python
import logging

from chipcompiler.data import StepMetrics, Workspace, WorkspaceStep, log_workspace_step


def load_eda_module(eda_tool: str):
    """
    Load and return the EDA tool module based on the given eda tool name.
    """

    def check_module(eda_module):
        functions = ["is_eda_exist", "build_step_space", "build_step_config", "run_step"]

        for func in functions:
            if not hasattr(eda_module, func):
                return False
        return True

    import importlib

    module_alias = {"klayout": "klayout_tool", "dreamplace": "ecc_dreamplace"}
    module_name = module_alias.get(eda_tool, eda_tool)

    try:
        eda_module = importlib.import_module(f"chipcompiler.tools.{module_name}")
    except Exception as e:
        logging.error(f"Error load module {eda_tool}: {e}")
        return None

    # check eda tool exist
    if not check_module(eda_module):
        functions = ["is_eda_exist", "build_step_space", "build_step_config", "run_step"]
        missing = [f for f in functions if not hasattr(eda_module, f)]
        logging.error("EDA tool '%s': module loaded but missing interface: %s", eda_tool, missing)
        return None

    if not eda_module.is_eda_exist():
        logging.error(
            "EDA tool '%s': dependency check failed (is_eda_exist returned False)", eda_tool
        )
        return None

    return eda_module


def load_eda_builder_module(eda_tool: str):
    """Load the builder-only module for an EDA tool without dependency checks."""
    import importlib

    module_alias = {"klayout": "klayout_tool", "dreamplace": "ecc_dreamplace"}
    module_name = module_alias.get(eda_tool, eda_tool)

    try:
        return importlib.import_module(f"chipcompiler.tools.{module_name}.builder")
    except Exception as exc:
        logging.error("Error load builder module %s: %s", eda_tool, exc)
        return None


def create_step(
    workspace: Workspace,
    step: str,
    eda: str,
    input_def: str,
    input_verilog: str,
    output_def: str = None,
    output_verilog: str = None,
    output_gds: str = None,
    build_config: bool = True,
) -> WorkspaceStep:
    """
    Create and return an EDA tool instance based on the given step and EDA
    tool name.

    Args:
        workspace: Workspace that owns the step.
        step: Flow step name.
        eda: EDA tool name.
        input_def: DEF input path for the step.
        input_verilog: Verilog input path for the step.
        output_def: Optional DEF output path override.
        output_verilog: Optional Verilog output path override.
        output_gds: Optional GDS output path override.
        build_config: When ``True``, regenerate the tool config files for the
            step. When ``False``, keep any existing config files in the step
            workspace and only rebuild the in-memory ``WorkspaceStep`` object.
    """
    if build_config:
        eda_module = load_eda_module(eda)
    else:
        eda_module = load_eda_builder_module(eda)

    if eda_module is None or not hasattr(eda_module, "build_step"):
        return None

    # build step
    step = eda_module.build_step(
        workspace=workspace,
        step_name=step,
        input_def=input_def,
        input_verilog=input_verilog,
        output_def=output_def,
        output_verilog=output_verilog,
        output_gds=output_gds,
    )

    # build step sub workspace
    eda_module.build_step_space(step)

    # update config
    if build_config:
        eda_module.build_step_config(workspace, step)

    return step


def run_step(
    workspace: Workspace, step: WorkspaceStep, ecc_module=None, regenerate_config: bool = True
) -> bool:
    """
    Run the given step using the provided EDA engine.

    Args:
        workspace: Workspace that owns the step.
        step: Step to execute.
        ecc_module: Optional shared ECC module.
        regenerate_config: When ``True``, regenerate step config files before
            execution. When ``False``, run with the existing config files
            already present in the workspace.
    """
    # check eda tool exist
    eda_module = load_eda_module(step.tool)
    if eda_module is None:
        return False

    # update config
    if regenerate_config:
        eda_module.build_step_config(workspace, step)

    log_workspace_step(step, workspace.logger)

    return eda_module.run_step(workspace=workspace, step=step, ecc_module=ecc_module)


def save_layout_image(workspace: Workspace, step: WorkspaceStep) -> bool:
    """
    Save the layout image for the given step.
    """
    # check eda tool exist
    eda_module = load_eda_module("klayout")
    if eda_module is None:
        return False

    from chipcompiler.tools.klayout_tool.runner import save_gds_image

    return save_gds_image(workspace=workspace, step=step)


def build_step_metrics(workspace: Workspace, step: WorkspaceStep) -> StepMetrics:
    """
    build step metrics
    """
    eda_module = load_eda_module(step.tool)
    if eda_module is None:
        return None

    metrics = eda_module.build_step_metrics(workspace=workspace, step=step)

    return metrics


def get_step_info(workspace: Workspace, step: WorkspaceStep, id: str) -> dict:
    """
    get step info by step and command id, return dict as resource definition
    """
    eda_module = load_eda_module(step.tool)
    if eda_module is None:
        return None

    return eda_module.get_step_info(workspace=workspace, step=step, id=id)
