from __future__ import annotations

from chipcompiler.data import Workspace, WorkspaceStep, log_workspace_step
from chipcompiler.tools.eda import load_eda_module

from .data import reapply_materialized_candidate_config


def run_step(workspace: Workspace, step: WorkspaceStep, ecc_module=None) -> bool:
    eda_module = load_eda_module(step.tool, check_dependency=step.tool != "sizer")
    if eda_module is None:
        return False
    eda_module.build_step_config(workspace, step)
    reapply_materialized_candidate_config(workspace, step.name)
    log_workspace_step(step, workspace.logger)
    return eda_module.run_step(workspace=workspace, step=step, ecc_module=ecc_module)
