from chipcompiler.data import Workspace, WorkspaceStep, log_workspace_step
from chipcompiler.tools.eda import load_eda_module

from .data import reapply_materialized_candidate_config
from .data.parameter_runtime_observer import run_with_parameter_observation
from .runtime_env import isolated_sizer_loader_environment


def run_step(workspace: Workspace, step: WorkspaceStep, ecc_module=None) -> bool:
    eda_module = load_eda_module(step.tool, check_dependency=step.tool != "sizer")
    if eda_module is None:
        return False
    eda_module.build_step_config(workspace, step)
    materialization = reapply_materialized_candidate_config(workspace, step.name)
    log_workspace_step(step, workspace.logger)

    def run_tool():
        if step.tool != "sizer":
            return eda_module.run_step(workspace=workspace, step=step, ecc_module=ecc_module)
        with isolated_sizer_loader_environment():
            return eda_module.run_step(workspace=workspace, step=step, ecc_module=ecc_module)

    return run_with_parameter_observation(
        workspace,
        step,
        materialization,
        run_tool,
    )
