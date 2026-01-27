#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from chipcompiler.data import Workspace, WorkspaceStep, StepMetrics, save_metrics
from chipcompiler.utility import json_read


def build_step_metrics(workspace: Workspace,
                       step: WorkspaceStep) -> StepMetrics:
    """
    Build and persist synthesis metrics from Yosys stat JSON.
    Args:
        workspace (Workspace): The current workspace.
        step (WorkspaceStep): The synthesis step to extract metrics from.
    Returns:
        StepMetrics: The populated step metrics object, or None if not available.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis.get('metrics', '')

    stat_json_path = step.feature.get('stat')
    data = json_read(stat_json_path)
    if not data:
        return None

    design_data = data.get('design', {})

    metrics = {
        "Step": step.name,
        "Tool": step.tool,
        "Total cells": design_data.get("num_cells", 0),
        "Total area": round(design_data.get("area", 0.0), 2),
        "Number of wires": design_data.get("num_wires", 0),
        "Number of ports": design_data.get("num_port_bits", 0),
    }

    step_metrics.data = metrics

    report = (
        f"{step.name} synthesis metrics from yosys stat. "
        f"Total cells: {metrics['Total cells']}, "
        f"Area: {metrics['Total area']}"
    )
    step_metrics.report.append(("", report))

    if save_metrics(step_metrics):
        return step_metrics
    return None

def get_step_info(workspace: Workspace, 
                  step: WorkspaceStep,
                  id : str) -> dict:
    """
    get step info by step and command id, return dict as resource definition
    """
    def build_metrics() -> dict:
        metrics = build_step_metrics(workspace=workspace,
                                     step=step)
        info = {
            "metrics" : metrics.path
        }
        
        return info
    
    def build_layout() -> dict:
        info = {
            "image" : step.output.get("image", ""),
        }
        
        info.update(build_metrics())
        
        return info
    
    def build_views() -> dict:
        info = {}
        
        info.update(build_layout())
        
        info["information"] = {}
        
        return info
    
    step_info = {}
    
    match id:
        case "views":
            step_info = build_views()
        case "layout":
            step_info = build_layout()
        case "metrics":
            step_info = build_metrics()

    return step_info