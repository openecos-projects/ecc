#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import sys
import os
       
from chipcompiler.data import WorkspaceStep, Workspace, StateEnum, StepEnum
from chipcompiler.tools.iEDA.module import IEDAModule
from chipcompiler.tools.iEDA.utility import is_eda_exist

def create_db_engine(workspace: Workspace,
                     step: WorkspaceStep) -> None:
    """"""
    if not is_eda_exist():
        return False
    
    from chipcompiler.tools.iEDA.module import IEDAModule
    eda_inst = IEDAModule()
    
    eda_inst.init_config(flow_config=step.config["flow"],
                         db_config=step.config["db"],
                         output_dir=step.data["dir"],
                         feature_dir=step.feature["dir"])
    
    eda_inst.init_techlef(workspace.pdk.tech)
    eda_inst.init_lefs(workspace.pdk.lefs)
    
    # if db def exist, read db def
    if os.path.exists(step.input["def"]):
        eda_inst.read_def(step.input["def"])    
    else:
        #else, read step output verilog
        if os.path.exists(step.input["verilog"]):
            eda_inst.read_verilog(verilog=step.input["verilog"],
                                  top_module=workspace.design.top_module)
        else:
            return None
    
    return eda_inst

def save_data(step: WorkspaceStep,
              module : IEDAModule) -> bool:
    """
    module is iEDA module from db engine, 
    eda instacnce may initialize data from this module if module has been set
    """
    if module is None:
        return FALSE
    
    module.def_save(def_path=step.output["def"])
    module.verilog_save(output_verilog=step.output["verilog"])
    module.feature_sammry(json_path=step.feature["db"])
    module.feature_step(step=step.name,
                        json_path=step.feature["step"])
    
    return True
    
def run_step(workspace: Workspace,
             step: WorkspaceStep,
             module : IEDAModule = None) -> bool:
    if not is_eda_exist():
        return StateEnum.Invalid
        
    state = StateEnum.Invalid
    match(step.name):
        case StepEnum.NETLIST_OPT.value:
            state = run_net_opt(workspace=workspace, 
                                step=step, 
                                module=module)
        case StepEnum.PLACEMENT.value:
            state = run_placement(workspace=workspace, 
                                  step=step, 
                                  module=module)
            
    return state

def run_net_opt(workspace: Workspace,
                step: WorkspaceStep,
                module : IEDAModule = None) -> bool:
    """
    module is iEDA module from db engine, 
    eda instacnce may initialize data from this module if module has been set
    """
    if module is not None:
        # copy data from module, but not set module to eda inst
        # TBD
        eda_inst = module
    else:
        # init iEDA module
        eda_inst = create_db_engine(workspace=workspace,
                                    step=step)
    
    if eda_inst is not None:
        eda_inst.run_net_opt(config=step.config[f"{StepEnum.NETLIST_OPT.value}"])
        
        return save_data(step=step, module=eda_inst)
    
def run_placement(workspace: Workspace,
                  step: WorkspaceStep,
                  module : IEDAModule = None) -> bool:
    """
    module is iEDA module from db engine, 
    eda instacnce may initialize data from this module if module has been set
    """
    if module is not None:
        # copy data from module, but not set module to eda inst
        # TBD
        eda_inst = module
    else:
        # init iEDA module
        eda_inst = create_db_engine(workspace=workspace,
                                    step=step)
    
    if eda_inst is not None:
        eda_inst.run_placement(config=step.config[f"{StepEnum.PLACEMENT.value}"])
        
        return save_data(step=step, module=eda_inst)