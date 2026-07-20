#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from chipcompiler.data import Workspace, WorkspaceStep
from chipcompiler.tools.yosys.metrics import build_step_metrics
from chipcompiler.utility import dict_to_str
from chipcompiler.utility.path import stringify_paths


def get_step_info(workspace: Workspace, 
                  step: WorkspaceStep,
                  id : str) -> dict:
    """
    get step info by step and command id, return dict as resource definition
    """
    step_info = {}
    
    match id:
        case "views":
            step_info = build_views(workspace=workspace, step=step)
        case "layout":
            step_info = build_layout(workspace=workspace, step=step)
        case "metrics":
            step_info = build_metrics(workspace=workspace, step=step)
        case "subflow":
            step_info = build_subflow(workspace=workspace, step=step)
        case "analysis":
            step_info = build_analysis(workspace=workspace, step=step)
        case "maps":
            step_info = build_maps(workspace=workspace, step=step)
        case "checklist":
            step_info = build_checklist(workspace=workspace, step=step)
        case "config":
            step_info = build_config(workspace=workspace, step=step)

    workspace.logger.log_section(f"[yosys] get step info, id = {id}")
    workspace.logger.info(f"{dict_to_str(step_info)}")

    return step_info

def build_views(workspace: Workspace, 
                step: WorkspaceStep) -> dict:
    info = {
        "image" : stringify_paths(step.output.get("image", "")),
        "metrics" : stringify_paths(step.analysis.metrics or ""),
        "information" : {}
    }
    
    return info

def build_layout(workspace: Workspace, 
                 step: WorkspaceStep) -> dict:
    info = {
        "image" : stringify_paths(step.output.get("image", "")),
    }
    
    return info

def build_metrics(workspace: Workspace, 
                  step: WorkspaceStep) -> dict:
    info = {
        "metrics" : stringify_paths(step.analysis.metrics or "")
    }
    
    return info

def build_subflow(workspace: Workspace, 
                  step: WorkspaceStep) -> dict:       
    info = {
        "path" : stringify_paths(step.subflow.get("path", ""))
    }
    
    return info


def build_config(workspace: Workspace, step: WorkspaceStep) -> dict:
    return {"path": stringify_paths(workspace.config.get("flow", ""))}

def build_analysis(workspace: Workspace, 
                   step: WorkspaceStep) -> dict:          
    info = {
        "metrics" : stringify_paths(step.analysis.metrics or ""),
        "data summary" : stringify_paths(step.feature.get("stat", "")),
        "step report" : stringify_paths(step.report.get("check", ""))
    }
    
    return info

def build_maps(workspace: Workspace, 
                   step: WorkspaceStep) -> dict:          
    info = {
        
    }
    
    return info

def build_checklist(workspace: Workspace, 
                    step: WorkspaceStep) -> dict:          
    info = {
        "path" : stringify_paths(step.checklist.get("path", ""))
    }
    
    return info
