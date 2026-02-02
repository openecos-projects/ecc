#!/usr/bin/env python
from chipcompiler.data import Workspace, WorkspaceStep


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

    return step_info

def build_views(workspace: Workspace, 
                step: WorkspaceStep) -> dict:
    info = {
        "image" : step.output.get("image", ""),
        "metrics" : step.analysis.get('metrics', ''),
        "information" : {}
    }
    
    return info

def build_layout(workspace: Workspace, 
                 step: WorkspaceStep) -> dict:
    info = {
        "image" : step.output.get("image", ""),
    }
    
    return info

def build_metrics(workspace: Workspace, 
                  step: WorkspaceStep) -> dict:
    info = {
        "metrics" : step.analysis.get('metrics', '')
    }
    
    return info

def build_subflow(workspace: Workspace, 
                  step: WorkspaceStep) -> dict:       
    info = {
        "path" : step.subflow.get("path", "")
    }
    
    return info

def build_analysis(workspace: Workspace, 
                   step: WorkspaceStep) -> dict:          
    info = {
        "metrics" : step.analysis.get("metrics", ""),
        "data summary" : step.feature.get("stat", ""),
        "step report" : step.report.get("check", "")
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
        "path" : step.checklist.get("path", "")
    }
    
    return info