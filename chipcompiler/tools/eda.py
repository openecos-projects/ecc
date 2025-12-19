#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from chipcompiler.workspaces import Workspace, WorkspaceStep, PDK, Parameters
import logging

def load_eda_module(eda_tool: str):
    """
    Load and return the EDA tool module based on the given eda tool name.
    """
    import importlib    
    eda_module = importlib.import_module(f"chipcompiler.tools.{eda_tool}")
    
    # check eda tool exist
    if not eda_module.is_eda_exist():
        logging.error(f"EDA tool : {eda_tool} not found!")
        return None
    
    return eda_module

def create_workspace(directory : str,
                     origin_def : str,
                     origin_verilog : str,
                     pdk : PDK,
                     parameters : Parameters) -> Workspace:
    # create workspace directory
    import os
    os.makedirs(directory, exist_ok=True)
    
    # create workspace instance
    workspace = Workspace()
    workspace.directory = directory
    workspace.design.name = parameters.data["Design"]
    workspace.design.top_module = parameters.data["Top module"]         
    workspace.pdk = pdk
    workspace.parameters = parameters
    
    # update orign files to workspace origin folder
    os.makedirs(f"{directory}/origin", exist_ok=True)

    import shutil
    if os.path.exists(origin_def):
        shutil.copy(origin_def, f"{directory}/origin/{os.path.basename(origin_def)}")
        workspace.design.origin_def = f"{directory}/origin/{os.path.basename(origin_def)}"
    if os.path.exists(origin_verilog):
        shutil.copy(origin_verilog, f"{directory}/origin/{os.path.basename(origin_verilog)}")
        workspace.design.origin_verilog = f"{directory}/origin/{os.path.basename(origin_verilog)}"
    if os.path.exists(pdk.sdc):
        shutil.copy(pdk.sdc, f"{directory}/origin/{os.path.basename(pdk.sdc)}")
        workspace.pdk.sdc = f"{directory}/origin/{os.path.basename(pdk.sdc)}"
    if os.path.exists(pdk.spef):
        shutil.copy(pdk.spef, f"{directory}/origin/{os.path.basename(pdk.spef)}")
        workspace.pdk.spef = f"{directory}/origin/{os.path.basename(pdk.spef)}"
    
    return workspace

def create_step(workspace : Workspace, 
               step : str, 
               eda : str,
               input_def : str,
               input_verilog : str,
               output_def : str = None,
               output_verilog : str = None,
               output_gds : str = None) -> WorkspaceStep:
    """
    Create and return an EDA tool instance based on the given step and eda tool name.
    """
    # check eda tool exist
    eda_module = load_eda_module(eda)
    if eda_module is None:
        return None
    
    # build step
    step = eda_module.build_step(workspace=workspace,
                                 step_name=step,
                                 input_def=input_def,
                                 input_verilog=input_verilog,
                                 output_def=output_def,
                                 output_verilog=output_verilog,
                                 output_gds=output_gds)
    
    # build step sub workspace
    eda_module.build_step_space(step)
    
    # update config
    eda_module.build_step_config(workspace, step, workspace.parameters)
    
    return step

def run_step(workspace: Workspace,
             step: WorkspaceStep) -> bool:
    """
    Run the given step using the provided EDA engine.
    """
    # check eda tool exist
    eda_module = load_eda_module(step.tool)
    if eda_module is None:
        return False
    
    return eda_module.run_step(workspace, step)