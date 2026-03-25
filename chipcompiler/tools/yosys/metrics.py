#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from chipcompiler.data import Workspace, WorkspaceStep, StepMetrics, save_metrics
from chipcompiler.utility import json_read, dict_to_str


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
        "Tool": step.tool,
        "Cell number": design_data.get("num_cells", 0),
        "Cell area": round(design_data.get("area", 0.0), 2),
        "Wire number": design_data.get("num_wires", 0),
        "Port number": design_data.get("num_port_bits", 0),
    }

    step_metrics.data = metrics

    report = (
        f"{step.name} synthesis metrics from yosys stat. "
        f"Total cells: {metrics['Cell number']}, "
        f"Area: {metrics['Cell area']}"
    )
    step_metrics.report.append(("", report))
    
    workspace.logger.info("\nmetrics - \n%s", dict_to_str(step_metrics.data))

    if save_metrics(step_metrics):
        return step_metrics
    return None