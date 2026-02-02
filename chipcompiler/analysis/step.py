#!/usr/bin/env python
from chipcompiler.data import StepMetrics, Workspace, WorkspaceStep, load_metrics, save_metrics


class StepMetricsBuilder:
    """
    A class to hold various analysis metrics for chip designs.
    """
    def __init__(self, workspace: Workspace):
        self.workspace = workspace
    
    def load(self, step : WorkspaceStep) -> StepMetrics:
        """
        Load step metrics from the step analysis metrics file.
        """
        step_metrics = load_metrics(step.analysis['metrics'])
        return step_metrics
    
    def save(self, step: WorkspaceStep, step_metrics : StepMetrics) -> bool:
        """
        save step metrics to the step analysis metrics file.
        """
        
        save_metrics(step_metrics)