#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import sys
import os
       
from chipcompiler.data import WorkspaceStep, Workspace, Parameters
from chipcompiler.tools.iEDA.engine import IEDAEngine
from chipcompiler.tools.iEDA.utility import is_eda_exist

def create_db_engine(workspace: Workspace,
                     step: WorkspaceStep) -> None:
    """"""
    if not is_eda_exist():
        return False
    
    from chipcompiler.tools.iEDA.engine import IEDAEngine
    eda_inst = IEDAEngine()
    
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
    
def run_step(workspace: Workspace,
             step: WorkspaceStep) -> bool:
    if not is_eda_exist():
        return False
    eda_inst = IEDAEngine()
    
    
    return True