#!/usr/bin/env python
from chipcompiler.data import (
    EccStep,
    StepMetrics,
    Workspace,
)
from chipcompiler.tools.ecc.subflow import EccSubFlow


def build_step_metrics(
    workspace: Workspace, step: EccStep, subflow: EccSubFlow = None
) -> StepMetrics:
    """
    Build and return a StepMetrics instance for the given workspace step.
    """
    from chipcompiler.tools.ecc import build_step_metrics as ecc_build_step_metrics

    return ecc_build_step_metrics(workspace=workspace, step=step, subflow=subflow)
