"""Run iEMIR on the routed database using iPW's per-instance power output."""

from pathlib import Path

from chipcompiler.data import EccStep, StateEnum, StepEnum, Workspace
from chipcompiler.data.handshake import load_request, power_source
from chipcompiler.data.step import StepDirectories
from chipcompiler.data.types import DesignState
from chipcompiler.tools.ecc.emir_artifacts import publish_emir_reports
from chipcompiler.tools.ecc.emir_model import SYNTHETIC_NOTICE, inspect_model
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.tools.ecc.power_artifacts import instance_power_path
from chipcompiler.tools.ecc.subflow import EccSubFlow, EccSubFlowEnum
from chipcompiler.utility import json_read, json_write


def run_emir(workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None) -> bool:
    # Share the runner's database/artifact lifecycle without eagerly importing
    # the dispatcher back into this step module.
    from chipcompiler.tools.ecc import runner

    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)
    config = json_read(workspace.config[StepEnum.EMIR.value])
    technology_file = config["technology_file_path"]
    if not technology_file:
        workspace.logger.error(
            "EMIR model is missing; select an EM resource with ecc pdk configure "
            "or set emir.synthetic_model=ics55 for non-signoff flow testing. Config: %s",
            workspace.config[StepEnum.EMIR.value],
        )
        sub_flow.update_step(EccSubFlowEnum.run_emir.value, StateEnum.Imcomplete)
        return False

    model = inspect_model(technology_file)
    if model.synthetic:
        workspace.logger.warning(SYNTHETIC_NOTICE)
    if step.report.dir is not None:
        from chipcompiler.pdk.manifest import file_digest

        json_write(
            step.report.dir / "model.json",
            {
                "technology_file_path": model.path,
                "sha256": file_digest(Path(model.path)),
                "model_kind": "synthetic" if model.synthetic else "provided",
                "qualification": "not_for_signoff" if model.synthetic else "not_assessed",
                "notice": SYNTHETIC_NOTICE
                if model.synthetic
                else "Model qualification not assessed.",
            },
        )

    ecc_module = runner.get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)
    if ecc_module is None:
        sub_flow.update_step(EccSubFlowEnum.load_data.value, StateEnum.Imcomplete)
        return False
    sub_flow.update_step(EccSubFlowEnum.load_data.value, StateEnum.Success)

    spef_path = _typical_spef_path(workspace, step, runner)

    sub_flow.update_step(EccSubFlowEnum.run_emir.value, StateEnum.Ongoing)
    initialized = False
    try:
        pdn_directory, power_directory = _upstream_directories(workspace, step)
        initialized = ecc_module.init_emir(
            output_dir=step.data.steps[StepEnum.EMIR.value],
            instance_power_file_path=instance_power_path(power_directory),
            technology_file_path=technology_file,
            ploc_file_path=pdn_directory / "data" / "fp" / "pdn_generator" / "power.ploc",
            spef_path=spef_path,
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


def _typical_spef_path(workspace: Workspace, step: EccStep, runner) -> str:
    """The typical corner's SPEF, or "" when the step has no parasitics."""
    if not runner.has_parasitics(workspace, step):
        return ""
    item = runner.typical_signoff_item(runner.collect_sta_signoff_items(workspace, step))
    return item["spef_file"] if item is not None else ""


def _upstream_directories(workspace: Workspace, step: EccStep) -> tuple[Path, Path]:
    """The steps that built the power grid and analyzed power, from req.json.

    A grid the project declares instead of building has no upstream step; it
    is read from the post_floorplan directory the ledger records. Power comes
    as :func:`power_source` resolves it, including an inherited power analysis.
    """
    if step.directory is None:
        raise ValueError(f"{step.name} step directory is not configured")
    request = load_request(Path(step.directory))
    power_directory = power_source(request)
    if power_directory is None:
        raise ValueError(
            f"{step.name} has no power analysis: no successful upstream power_analysis "
            "run and no inherited power outputs"
        )
    pdn = request.upstream.get(DesignState.PDN)
    pdn_directory = (
        Path(workspace.directory) / pdn.step_directory
        if pdn is not None
        else StepDirectories.of(workspace).path(StepEnum.POST_FLOORPLAN.value)
    )
    return pdn_directory, power_directory
