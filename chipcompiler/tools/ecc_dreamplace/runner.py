#!/usr/bin/env python

from chipcompiler.data import EccStep, StateEnum, StepEnum, Workspace
from chipcompiler.tools.ecc import EccSubFlow, EccSubFlowEnum, ECCToolsModule
from chipcompiler.tools.ecc import runner as ecc_runner

from .checklist import DreamplaceChecklist
from .module import DreamplaceModule, DreamplaceRunMode
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
        case StepEnum.MACRO_PLACEMENT.value:
            state = run_macro_placement(workspace=workspace, step=step, ecc_module=ecc_module)
        case StepEnum.PLACEMENT.value:
            state = run_placement(workspace=workspace, step=step, ecc_module=ecc_module)
        case StepEnum.LEGALIZATION.value:
            state = run_legalization(workspace=workspace, step=step, ecc_module=ecc_module)

    return state


def _run_placement_mode(
    workspace: Workspace,
    step: EccStep,
    ecc_module: ECCToolsModule | None,
    mode: DreamplaceRunMode,
) -> bool:
    result = False

    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)

    ecc_module = ecc_runner.get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)

    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)
        dreamplace_module = DreamplaceModule(
            workspace=workspace,
            step=step,
            ecc_module=ecc_module,
            input_def=step.input.def_,
            input_verilog=step.input.verilog,
            output_def=step.output.def_,
            output_verilog=step.output.verilog,
        )
        run_name = (
            EccSubFlowEnum.run_macro_placement
            if mode is DreamplaceRunMode.MACRO_PLACEMENT
            else EccSubFlowEnum.run_placement
        )
        run_method = (
            dreamplace_module.run_macro_placement
            if mode is DreamplaceRunMode.MACRO_PLACEMENT
            else dreamplace_module.run_placement
        )
        result = run_method()
        if not result:
            sub_flow.update_step(
                step_name=run_name.value, state=StateEnum.Imcomplete
            )
            return False

        if mode is DreamplaceRunMode.PLACEMENT:
            ecc_module.feature_placement_map(json_path=step.feature.map)

        sub_flow.update_step(step_name=run_name.value, state=StateEnum.Success)

        result = ecc_runner.save_data(
            workspace=workspace, step=step, ecc_module=ecc_module, feature_step=False
        )

        sub_flow.update_step(
            step_name=EccSubFlowEnum.save_data.value,
            state=StateEnum.Success if result else StateEnum.Imcomplete,
        )
        if not result:
            return False

        run_analysis(workspace=workspace, step=step, subflow=sub_flow)

    return result


def run_macro_placement(
    workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None
) -> bool:
    """Run full DreamPlace optimization and commit only eligible hard macros."""
    return _run_placement_mode(
        workspace=workspace,
        step=step,
        ecc_module=ecc_module,
        mode=DreamplaceRunMode.MACRO_PLACEMENT,
    )


def run_placement(
    workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None
) -> bool:
    """Run placement."""
    return _run_placement_mode(
        workspace=workspace,
        step=step,
        ecc_module=ecc_module,
        mode=DreamplaceRunMode.PLACEMENT,
    )


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
