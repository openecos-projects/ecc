"""Run iEMIR on the routed database using iPW's per-instance power output."""

from pathlib import Path

from chipcompiler.data import EccStep, StateEnum, StepEnum, Workspace
from chipcompiler.data.types import AnalysisData, DesignState
from chipcompiler.data.workspace.step_directories import StepDirectories
from chipcompiler.data.workspace.step_handshake import load_request
from chipcompiler.tools.ecc.emir_artifacts import publish_emir_reports
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.tools.ecc.power_artifacts import instance_power_path
from chipcompiler.tools.ecc.subflow import EccSubFlow, EccSubFlowEnum
from chipcompiler.utility import json_read


def run_emir(workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None) -> bool:
    # Share the runner's database/artifact lifecycle without eagerly importing
    # the dispatcher back into this step module.
    from chipcompiler.tools.ecc import runner

    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)
    config = json_read(workspace.config[StepEnum.EMIR.value])
    technology_file = config["technology_file_path"]
    if not technology_file:
        workspace.logger.error(
            "EMIR technology_file_path is a placeholder; configure it in %s before running",
            workspace.config[StepEnum.EMIR.value],
        )
        sub_flow.update_step(EccSubFlowEnum.run_emir.value, StateEnum.Imcomplete)
        return False

    ecc_module = runner.get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)
    if ecc_module is None:
        sub_flow.update_step(EccSubFlowEnum.load_data.value, StateEnum.Imcomplete)
        return False
    sub_flow.update_step(EccSubFlowEnum.load_data.value, StateEnum.Success)

    sub_flow.update_step(EccSubFlowEnum.run_emir.value, StateEnum.Ongoing)
    initialized = False
    try:
        pdn_directory, power_directory = _upstream_directories(workspace, step)
        initialized = ecc_module.init_emir(
            output_dir=step.data.steps[StepEnum.EMIR.value],
            instance_power_file_path=instance_power_path(power_directory),
            technology_file_path=technology_file,
            ploc_file_path=pdn_directory / "data" / "fp" / "pdn_generator" / "power.ploc",
        )
        if not initialized:
            workspace.logger.error("Failed to initialize EMIR")
            sub_flow.update_step(EccSubFlowEnum.run_emir.value, StateEnum.Imcomplete)
            return False
        if not ecc_module.run_emir():
            workspace.logger.error("EMIR analysis failed")
            sub_flow.update_step(EccSubFlowEnum.run_emir.value, StateEnum.Imcomplete)
            return False
    except Exception:
        sub_flow.update_step(EccSubFlowEnum.run_emir.value, StateEnum.Imcomplete)
        raise
    finally:
        if initialized:
            ecc_module.destroy_emir()

    sub_flow.update_step(EccSubFlowEnum.run_emir.value, StateEnum.Success)
    if not runner.save_data(
        workspace=workspace, step=step, ecc_module=ecc_module, feature_step=False
    ):
        sub_flow.update_step(EccSubFlowEnum.save_data.value, StateEnum.Imcomplete)
        return False
    report_dir = step.report.dir
    if report_dir is None:
        workspace.logger.warning("EMIR report directory is not configured")
    else:
        try:
            publish_emir_reports(
                data_dir=step.data.steps[StepEnum.EMIR.value],
                report_dir=report_dir,
            )
        except Exception as error:
            workspace.logger.warning("Failed to publish EMIR reports: %s", error)
    sub_flow.update_step(EccSubFlowEnum.save_data.value, StateEnum.Success)
    return True


def _upstream_directories(workspace: Workspace, step: EccStep) -> tuple[Path, Path]:
    """The steps that built the power grid and analyzed power, from req.json.

    A grid the project declares instead of building has no upstream step; it
    is read from the postFloorplan directory the ledger records.
    """
    if step.directory is None:
        raise ValueError(f"{step.name} step directory is not configured")
    upstream = load_request(Path(step.directory)).upstream
    power = upstream.get(AnalysisData.POWER)
    if power is None:
        raise ValueError(f"{step.name} has no upstream power analysis")
    pdn = upstream.get(DesignState.PDN)
    pdn_directory = (
        Path(workspace.directory) / pdn.step_directory
        if pdn is not None
        else StepDirectories.of(workspace).path(StepEnum.POST_FLOORPLAN.value)
    )
    return pdn_directory, Path(workspace.directory) / power.step_directory
