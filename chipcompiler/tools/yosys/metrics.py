#!/usr/bin/env python
from chipcompiler.data import StepMetrics, Workspace, YosysStep
from chipcompiler.tools.ecc.metrics import save_step_metrics
from chipcompiler.utility import dict_to_str, json_read


def build_step_metrics(workspace: Workspace, step: YosysStep) -> StepMetrics:
    """
    Build and persist synthesis metrics from Yosys stat JSON.
    Args:
        workspace (Workspace): The current workspace.
        step (WorkspaceStep): The synthesis step to extract metrics from.
    Returns:
        StepMetrics: The populated step metrics object, or None if not available.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis.metrics or ""

    stat_json_path = step.feature.stat or ""
    data = json_read(stat_json_path)
    if not data:
        return None

    design_data = data.get("design", {})

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

    if save_step_metrics(workspace, step, step_metrics):
        return step_metrics
    return None
