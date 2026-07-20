#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from __future__ import annotations

import os

from chipcompiler.data import EccStep, StateEnum, StepEnum, Workspace, WorkspaceStep

from chipcompiler.tools.ecc import runner as ecc_runner
from chipcompiler.tools.ecc import EccSubFlowEnum, EccSubFlow, ECCToolsModule

from .module import DreamplaceModule
from .checklist import DreamplaceChecklist
from .utility import is_eda_exist


def run_analysis(workspace: Workspace,
                 step: EccStep,
                 subflow : EccSubFlow):
    ecc_runner.run_analysis(workspace=workspace,
                            step=step,
                            subflow=subflow)

    checklist = DreamplaceChecklist(workspace=workspace,
                                    workspace_step=step,
                                    init_checklist=False)
    checklist.check()

def run_step(
    workspace: Workspace,
    step: EccStep,
    ecc_module: ECCToolsModule | None = None,
) -> bool:
    if not is_eda_exist():
        return False
    
    state = False
    match(step.name):
        case StepEnum.PLACEMENT.value:
            state = run_placement(workspace=workspace, 
                                  step=step, 
                                  ecc_module=ecc_module)
        case StepEnum.LEGALIZATION.value:
            state = run_legalization(workspace=workspace, 
                                     step=step, 
                                     ecc_module=ecc_module)
            
    return state


    
def run_placement(workspace: Workspace,
                  step: EccStep,
                  ecc_module : ECCToolsModule = None) -> bool:
    """
    run placement
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)
    
    ecc_module = ecc_runner.get_eda_instance(workspace=workspace,
                                           step=step,
                                           ecc_module=ecc_module)
    
    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        # run ecc dreamplace
        dreamplace_module = DreamplaceModule(
            workspace=workspace,
            step=step,
            ecc_module=ecc_module,
            input_def=step.input.def_ or "",
            input_verilog=step.input.verilog or "",
            output_def=step.output.def_ or "",
            output_verilog=step.output.verilog or "",
        )
        reslut = dreamplace_module.run_placement()
    
        ecc_module.feature_placement_map(json_path=step.feature.map)
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_placement.value, state=StateEnum.Success)
        
        reslut = ecc_runner.save_data(workspace=workspace, step=step, ecc_module=ecc_module, feature_step=False)
        
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        run_analysis(workspace=workspace, step=step, subflow=sub_flow)
    
    return reslut


def run_legalization(workspace: Workspace,
                     step: EccStep,
                     ecc_module : ECCToolsModule = None) -> bool:
    """
    run placement legalization
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace,
                          workspace_step=step)
    
    ecc_module = ecc_runner.get_eda_instance(workspace=workspace,
                                           step=step,
                                           ecc_module=ecc_module)
    
    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        # run ecc dreamplace
        dreamplace_module = DreamplaceModule(
            workspace=workspace,
            step=step,
            ecc_module=ecc_module,
            input_def=step.input.def_ or "",
            input_verilog=step.input.verilog or "",
            output_def=step.output.def_ or "",
            output_verilog=step.output.verilog or "",
        )
        reslut = dreamplace_module.run_legalization()
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_legalization.value, state=StateEnum.Success)
        
        reslut = ecc_runner.save_data(workspace=workspace, step=step, ecc_module=ecc_module, feature_step=False)
   
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        run_analysis(workspace=workspace, step=step, subflow=sub_flow)
    
    return reslut
