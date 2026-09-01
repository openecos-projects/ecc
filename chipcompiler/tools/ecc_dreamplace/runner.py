#!/usr/bin/env python

from dataclasses import replace
from pathlib import Path

from chipcompiler.data import EccStep, StateEnum, StepEnum, StepInput, Workspace
from chipcompiler.tools.ecc import EccSubFlow, EccSubFlowEnum, ECCToolsModule
from chipcompiler.tools.ecc import runner as ecc_runner

from .checklist import DreamplaceChecklist
from .module import DreamplaceModule
from .utility import is_eda_exist


def run_analysis(workspace: Workspace, step: EccStep, subflow: EccSubFlow):
    ecc_runner.run_analysis(workspace=workspace, step=step, subflow=subflow)

    checklist = DreamplaceChecklist(workspace=workspace, workspace_step=step, init_checklist=False)
    checklist.check()


def run_step(
    workspace: Workspace,
    step: EccStep,
    ecc_module: ECCToolsModule | None = None,
) -> bool:
    import logging

    logger = logging.getLogger(__name__)
    if not is_eda_exist():
        logger.error("DreamPlace tools not available for step %s", step.name)
        return False

    state = False
    match step.name:
        case StepEnum.PLACEMENT.value:
            state = run_placement(workspace=workspace, step=step, ecc_module=ecc_module)
        case StepEnum.LEGALIZATION.value:
            state = run_legalization(workspace=workspace, step=step, ecc_module=ecc_module)

    return state


def run_placement(
    workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None
) -> bool:
    """
    run placement
    """
    reslut = False

    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)

    ecc_module = ecc_runner.get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)

    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)

        # run ecc dreamplace
        dreamplace_module = DreamplaceModule(
            workspace=workspace,
            step=step,
            ecc_module=ecc_module,
            input_def=step.input.def_,
            input_verilog=step.input.verilog,
            output_def=step.output.def_,
            output_verilog=step.output.verilog,
        )
        reslut = dreamplace_module.run_placement()
        if not reslut:
            sub_flow.update_step(
                step_name=EccSubFlowEnum.run_placement.value, state=StateEnum.Imcomplete
            )
            return False

        ecc_module.feature_placement_map(json_path=step.feature.map)

        sub_flow.update_step(step_name=EccSubFlowEnum.run_placement.value, state=StateEnum.Success)

        reslut = ecc_runner.save_data(
            workspace=workspace, step=step, ecc_module=ecc_module, feature_step=False
        )

        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value, state=StateEnum.Success)

        run_analysis(workspace=workspace, step=step, subflow=sub_flow)

    return reslut


def run_legalization(
    workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None
) -> bool:
    """
    run placement legalization
    """
    reslut = False

    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)

    ecc_module = ecc_runner.get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)

    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)

        # run ecc dreamplace
        dreamplace_module = DreamplaceModule(
            workspace=workspace,
            step=step,
            ecc_module=ecc_module,
            input_def=step.input.def_,
            input_verilog=step.input.verilog,
            output_def=step.output.def_,
            output_verilog=step.output.verilog,
        )
        reslut = dreamplace_module.run_legalization()
        if not reslut:
            sub_flow.update_step(
                step_name=EccSubFlowEnum.run_legalization.value, state=StateEnum.Imcomplete
            )
            return False

        sub_flow.update_step(
            step_name=EccSubFlowEnum.run_legalization.value, state=StateEnum.Success
        )

        reslut = ecc_runner.save_data(
            workspace=workspace, step=step, ecc_module=ecc_module, feature_step=False
        )

        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value, state=StateEnum.Success)

        run_analysis(workspace=workspace, step=step, subflow=sub_flow)

    return reslut


def legalize_layout(
    workspace: Workspace,
    owner_step: EccStep,
    input_def: Path | None,
    input_verilog: Path | None,
) -> ECCToolsModule | None:
    """Legalize a layout for an owning step without owning that step's subflow."""
    import logging

    logger = logging.getLogger(__name__)
    if not is_eda_exist():
        logger.error(
            "DreamPlace tools not available for inner legalization of %s",
            owner_step.name,
        )
        return None

    if not workspace.config.get("dreamplace"):
        from chipcompiler.data import build_workspace_config_paths

        workspace.config["dreamplace"] = build_workspace_config_paths(workspace)["dreamplace"]
    dreamplace_config = workspace.config.get("dreamplace")
    if not dreamplace_config or not Path(dreamplace_config).is_file():
        logger.error(
            "DreamPlace config is missing for inner legalization of %s",
            owner_step.name,
        )
        return None

    load_step = replace(
        owner_step,
        input=StepInput(def_=input_def, verilog=input_verilog, db=None),
    )
    ecc_module = ecc_runner.create_db_engine(workspace, load_step)
    if ecc_module is None:
        logger.error(
            "Failed to rebuild ECC database for inner legalization of %s",
            owner_step.name,
        )
        return None

    keep_engine = False
    try:
        dreamplace_module = DreamplaceModule(
            workspace=workspace,
            step=owner_step,
            ecc_module=ecc_module,
            input_def=input_def,
            input_verilog=input_verilog,
            output_def=None,
            output_verilog=None,
        )
        if not dreamplace_module.run_legalization():
            logger.error("DreamPlace legalization failed for %s", owner_step.name)
            return None
        keep_engine = True
        return ecc_module
    finally:
        if not keep_engine:
            ecc_module.close()
