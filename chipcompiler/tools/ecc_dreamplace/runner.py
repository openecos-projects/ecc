#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from __future__ import annotations

import os

from chipcompiler.data import StateEnum, StepEnum, Workspace, WorkspaceStep

from chipcompiler.tools.ecc import runner as ecc_runner
from chipcompiler.tools.ecc import EccSubFlowEnum, EccSubFlow, ECCToolsModule

from .module import DreamplaceModule
from .utility import is_eda_exist

def run_step(
    workspace: Workspace,
    step: WorkspaceStep,
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
                  step: WorkspaceStep,
                  ecc_module : ECCToolsModule = None) -> bool:
    """
    run placement
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)
    
    ecc_inst = ecc_runner.get_eda_instance(workspace=workspace,
                                           step=step,
                                           ecc_module=ecc_module)
    
    if ecc_inst is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        # run ecc dreamplace
        dreamplace_module = DreamplaceModule(
            workspace=workspace,
            step=step,
            ecc_module=ecc_inst,
            input_def=step.input.get("def", ""),
            input_verilog=step.input.get("verilog", ""),
            output_def=step.output.get("def", ""),
            output_verilog=step.output.get("verilog", ""),
        )
        reslut = dreamplace_module.run_placement()
    
        ecc_inst.feature_placement_map(json_path=step.feature["map"])
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_placement.value, state=StateEnum.Success)
        
        reslut = ecc_runner.save_data(workspace=workspace, step=step, ecc_module=ecc_inst, feature_step=False)
        
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        ecc_runner.run_analysis(workspace = workspace, step = step, subflow = sub_flow)
    
    return reslut


def run_legalization(workspace: Workspace,
                     step: WorkspaceStep,
                     ecc_module : ECCToolsModule = None) -> bool:
    """
    run placement legalization
    """
    reslut = False
    
    sub_flow = EccSubFlow(workspace=workspace,
                          workspace_step=step)
    
    ecc_inst = ecc_runner.get_eda_instance(workspace=workspace,
                                           step=step,
                                           ecc_module=ecc_module)
    
    if ecc_inst is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        
        # run ecc dreamplace
        dreamplace_module = DreamplaceModule(
            workspace=workspace,
            step=step,
            ecc_module=ecc_inst,
            input_def=step.input.get("def", ""),
            input_verilog=step.input.get("verilog", ""),
            output_def=step.output.get("def", ""),
            output_verilog=step.output.get("verilog", ""),
        )
        reslut = dreamplace_module.run_legalization()
        
        sub_flow.update_step(step_name=EccSubFlowEnum.run_legalization.value, state=StateEnum.Success)
        
        reslut = ecc_runner.save_data(workspace=workspace, step=step, ecc_module=ecc_inst, feature_step=False)
   
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value,
                             state=StateEnum.Success) 
        
        ecc_runner.run_analysis(workspace = workspace, step = step, subflow = sub_flow)
    
    return reslut