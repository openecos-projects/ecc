from chipcompiler.data import EccStep, StepMetrics, Workspace


def build_step_metrics(workspace: Workspace, step: EccStep) -> StepMetrics | None:
    from chipcompiler.tools.ecc.metrics import build_metrics_legalization

    return build_metrics_legalization(workspace, step)
