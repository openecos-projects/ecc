#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from __future__ import annotations

import os

from chipcompiler.data import StateEnum, StepEnum, Workspace, WorkspaceStep
from chipcompiler.tools.ecc.checklist import EccChecklist
from chipcompiler.tools.ecc.metrics import build_step_metrics
from chipcompiler.tools.ecc.plot import ECCToolsPlot
from chipcompiler.tools.ecc.runner import (
    run_step as run_ecc_step,
    save_data,
)
from chipcompiler.tools.ecc.subflow import EccSubFlow, EccSubFlowEnum

from .module import ECCToolsModule
from .run_dreamplace import DreamPlace
from .utility import is_eda_exist


SUPPORTED_DREAMPLACE_STEPS = {
    StepEnum.PLACEMENT.value,
    StepEnum.LEGALIZATION.value,
}


def create_db_engine(workspace: Workspace, step: WorkspaceStep) -> ECCToolsModule | None:
    eda_inst = ECCToolsModule()
    eda_inst.init_config(
        flow_config=step.config["flow"],
        db_config=step.config["db"],
        output_dir=step.data["dir"],
        feature_dir=step.feature["dir"],
    )
    eda_inst.init_techlef(workspace.pdk.tech)
    eda_inst.init_lefs(workspace.pdk.lefs)

    if os.path.exists(step.input["def"]):
        eda_inst.read_def(step.input["def"])
        return eda_inst

    if os.path.exists(step.input["verilog"]):
        eda_inst.read_verilog(
            verilog=step.input["verilog"],
            top_module=workspace.design.top_module,
        )
        return eda_inst

    return None


def _run_analysis(workspace: Workspace, step: WorkspaceStep, subflow: EccSubFlow) -> None:
    build_step_metrics(workspace=workspace, step=step, subflow=subflow)
    ploter = ECCToolsPlot(workspace=workspace, step=step)
    ploter.plot()
    checklist = EccChecklist(workspace=workspace, workspace_step=step)
    checklist.check()


def _run_dreamplace_step(workspace: Workspace, step: WorkspaceStep) -> bool:
    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)
    sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)

    module = create_db_engine(workspace=workspace, step=step)
    if module is None:
        return False

    runner = DreamPlace(
        workspace=workspace,
        step=step,
        module=module,
        input_def=step.input.get("def", ""),
        input_verilog=step.input.get("verilog", ""),
        output_def=step.output.get("def", ""),
        output_verilog=step.output.get("verilog", ""),
    )

    if step.name == StepEnum.PLACEMENT.value:
        success = runner.run_placement()
        subflow_step = EccSubFlowEnum.run_placement.value
    else:
        success = runner.run_legalization()
        subflow_step = EccSubFlowEnum.run_legalization.value

    if not success:
        return False

    sub_flow.update_step(step_name=subflow_step, state=StateEnum.Success)

    success = save_data(workspace=workspace, step=step, module=module, feature_step=False)
    if not success:
        return False

    sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value, state=StateEnum.Success)
    _run_analysis(workspace=workspace, step=step, subflow=sub_flow)
    return True


def run_step(
    workspace: Workspace,
    step: WorkspaceStep,
    module: ECCToolsModule = None,
) -> bool:
    if step.name not in SUPPORTED_DREAMPLACE_STEPS:
        return run_ecc_step(workspace=workspace, step=step, module=module)

    if not is_eda_exist():
        return StateEnum.Invalid

    return _run_dreamplace_step(workspace=workspace, step=step)
