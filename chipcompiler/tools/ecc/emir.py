"""Run iEMIR on the routed database using iPW's per-instance power output."""

from chipcompiler.data import EccStep, StateEnum, StepEnum, Workspace
from chipcompiler.data.step import STEP_DIRECTORIES
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.tools.ecc.power_artifacts import workspace_instance_power_path
from chipcompiler.tools.ecc.subflow import EccSubFlow, EccSubFlowEnum
from chipcompiler.utility import json_read


def run_emir(workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None) -> bool:
    # Share the runner's database/artifact lifecycle without eagerly importing
    # the dispatcher back into this step module.
    from chipcompiler.tools.ecc import runner

    if workspace.directory is None:
        raise ValueError("EMIR requires a workspace directory")
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
        initialized = ecc_module.init_emir(
            output_dir=step.data.steps[StepEnum.EMIR.value],
            instance_power_file_path=workspace_instance_power_path(workspace.directory),
            technology_file_path=technology_file,
            ploc_file_path=(
                workspace.directory
                / STEP_DIRECTORIES[StepEnum.POST_FLOORPLAN.value]
                / "data"
                / "fp"
                / "pdn_generator"
                / "power.ploc"
            ),
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
    sub_flow.update_step(EccSubFlowEnum.save_data.value, StateEnum.Success)
    return True
