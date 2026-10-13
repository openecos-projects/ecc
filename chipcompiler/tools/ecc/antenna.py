"""Run iMJ's report-only antenna check on the routed physical database."""

import shutil

from chipcompiler.data import EccStep, StateEnum, StepEnum, Workspace
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.tools.ecc.subflow import EccSubFlow, EccSubFlowEnum


def run_antenna_check(
    workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None
) -> bool:
    from chipcompiler.tools.ecc import runner

    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)
    data_dir = step.data.steps[StepEnum.ANTENNA_CHECK.value]
    native_report = data_dir / "antenna_checker" / "antenna_check.rpt"
    report_path = step.report.step
    if report_path is None:
        raise ValueError("Antenna check report path is not configured")
    # A failed rerun must not expose an old report as the current result.
    native_report.unlink(missing_ok=True)
    report_path.unlink(missing_ok=True)

    ecc_module = runner.get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)
    if ecc_module is None:
        sub_flow.update_step(EccSubFlowEnum.load_data.value, StateEnum.Imcomplete)
        return False
    sub_flow.update_step(EccSubFlowEnum.load_data.value, StateEnum.Success)

    sub_flow.update_step(EccSubFlowEnum.check_antenna.value, StateEnum.Ongoing)
    completed = False
    try:
        if not ecc_module.init_mj(output_dir=data_dir):
            workspace.logger.error("Failed to initialize iMJ for antenna checking")
            return False
        try:
            checked = ecc_module.check_antenna()
        finally:
            destroyed = ecc_module.destroy_mj()
        if not checked or not destroyed:
            workspace.logger.error("iMJ antenna check failed")
            return False
        if not native_report.is_file():
            workspace.logger.error("Antenna check report is missing: %s", native_report)
            return False
        report_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(native_report, report_path)
        # Success means execution/reporting completed, not zero violations
        # or complete antenna-rule coverage in the technology/cell LEFs.
        completed = True
    finally:
        sub_flow.update_step(
            EccSubFlowEnum.check_antenna.value,
            StateEnum.Success if completed else StateEnum.Imcomplete,
        )

    if not runner.save_data(
        workspace=workspace, step=step, ecc_module=ecc_module, feature_step=False
    ):
        sub_flow.update_step(EccSubFlowEnum.save_data.value, StateEnum.Imcomplete)
        return False
    sub_flow.update_step(EccSubFlowEnum.save_data.value, StateEnum.Success)
    return True
