#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from chipcompiler.data import Workspace, WorkspaceStep, StepMetrics
import logging

def load_eda_module(eda_tool: str):
    """
    Load and return the EDA tool module based on the given eda tool name.
    """
    def check_module(eda_module):
        functions = [
            'is_eda_exist',
            'build_step_space',
            'build_step_config',
            'run_step'
        ]
        
        for func in functions:
            if not hasattr(eda_module, func):
                return False
        return True
    
    eda_module = None
    try:
        import importlib    
        eda_module = importlib.import_module(f"chipcompiler.tools.{eda_tool}")
        # check eda tool exist
        if not check_module(eda_module) or not eda_module.is_eda_exist():
            logging.error(f"EDA tool : {eda_tool} not found!")
            return None
    except Exception as e:    
        logging.error(f"Error load module {eda_tool}: {e}")
    finally:    
        return eda_module

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
    if eda_module is None \
        or not hasattr(eda_module, 'build_step'):
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
    eda_module.build_step_config(workspace, step)
    
    return step

def run_step(workspace: Workspace,
             step: WorkspaceStep,
             module = None) -> bool:
    """
    Run the given step using the provided EDA engine.
    """
    # check eda tool exist
    eda_module = load_eda_module(step.tool)
    if eda_module is None:
        return False
    
    return eda_module.run_step(workspace=workspace, 
                               step=step,
                               module=module)
    
def save_layout_image(workspace: Workspace,
                      step: WorkspaceStep) -> bool:
    """
    Save the layout image for the given step.
    """
    # check eda tool exist
    eda_module = load_eda_module("klayout")
    if eda_module is None:
        return False
    
    from chipcompiler.tools.klayout.runner import save_gds_image
    return save_gds_image(workspace=workspace,
                          step=step)
    
def build_step_metrics(workspace: Workspace, 
                       step: WorkspaceStep) -> StepMetrics:
    """
    build step metrics
    """
    eda_module = load_eda_module(step.tool)
    if eda_module is None:
        return False

    return eda_module.build_step_metrics(workspace=workspace,
                                         step=step)
    
def get_step_info(workspace: Workspace, 
                  step: WorkspaceStep,
                  id : str) -> dict:
    """
    get step info by step and command id, return dict as resource definition
    """
    eda_module = load_eda_module(step.tool)
    if eda_module is None:
        return None

    return eda_module.get_step_info(workspace=workspace,
                                    step=step,
                                    id=id)
    
class SubFlowBase:
    def notify_subflow(self, step : str,  subflow_path : str):
        from chipcompiler.server.sse import server_notify
        notify_inst = server_notify()
        notify_inst.notify_subflow(step, subflow_path)
        