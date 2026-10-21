#!/usr/bin/env python

from dataclasses import replace
from pathlib import Path

from chipcompiler.data import EccStep, StateEnum, StepEnum, StepInput, Workspace
from chipcompiler.data.workspace.macro_location import macro_placements
from chipcompiler.tools.ecc import EccSubFlow, EccSubFlowEnum, ECCToolsModule
from chipcompiler.tools.ecc import runner as ecc_runner
from chipcompiler.utility import json_read

from .checklist import DreamplaceChecklist
from .module import DreamplaceModule, DreamplaceRunMode
from .utility import is_eda_exist


def run_analysis(workspace: Workspace, step: EccStep, subflow: EccSubFlow):
    ecc_runner.run_analysis(workspace=workspace, step=step, subflow=subflow)

    checklist = DreamplaceChecklist(workspace=workspace, workspace_step=step, init_checklist=False)
    checklist.check()


def _placement_backend(workspace: Workspace) -> str:
    config_path = workspace.config.get("dreamplace")
    if not config_path:
        return "ieda"
    return str(json_read(config_path).get("place_io_engine", "ieda") or "ieda").lower()


def _is_terminal_placement(workspace: Workspace, step: EccStep) -> bool:
    """Return whether placement is the selected flow's terminal step."""
    steps = workspace.flow.steps()
    if not steps:
        return False
    selected = [item for item in steps if item.get("name") == step.name]
    return bool(selected) and steps[-1] is selected[-1]


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
        case StepEnum.DIFF_SIZING.value:
            state = run_diff_sizing(workspace=workspace, step=step, ecc_module=ecc_module)
        case StepEnum.LEGALIZATION.value:
            state = run_legalization(workspace=workspace, step=step, ecc_module=ecc_module)

    return state


def run_macro_placement(
    workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None
) -> bool:
    """Run macro-only placement between the two floorplan phases."""
    import logging

    logger = logging.getLogger(__name__)
    reslut = False
    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)

    ecc_module = ecc_runner.get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)

    if ecc_module is not None:
        sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)

        manual_placements = macro_placements(workspace)
        if manual_placements:
            logger.info(
                "macro.placements set (%d entries); skipping DreamPlace, using %s",
                len(manual_placements),
                workspace.config.get("macro_location", ""),
            )
            sub_flow.update_step(
                step_name=EccSubFlowEnum.macro_place.value, state=StateEnum.Success
            )
        else:
            dreamplace_module = DreamplaceModule(
                workspace=workspace,
                step=step,
                ecc_module=ecc_module,
                input_def=step.input.def_,
                input_verilog=step.input.verilog,
                output_def=step.output.def_,
                output_verilog=step.output.verilog,
            )
            reslut = dreamplace_module.run_macro_placement()
            if not reslut:
                sub_flow.update_step(
                    step_name=EccSubFlowEnum.macro_place.value, state=StateEnum.Imcomplete
                )
                return False

            reslut = ecc_module.tcl_save(workspace.config.get("macro_location", ""))
            if not reslut:
                sub_flow.update_step(
                    step_name=EccSubFlowEnum.macro_place.value, state=StateEnum.Imcomplete
                )
                return False

            sub_flow.update_step(
                step_name=EccSubFlowEnum.macro_place.value, state=StateEnum.Success
            )
        reslut = ecc_runner.save_data(
            workspace=workspace, step=step, ecc_module=ecc_module, feature_step=False
        )
        sub_flow.update_step(step_name=EccSubFlowEnum.save_data.value, state=StateEnum.Success)

    return reslut


def run_placement(
    workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None
) -> bool:
    return _run_placement_mode(
        workspace=workspace,
        step=step,
        ecc_module=ecc_module,
        mode=DreamplaceRunMode.PLACEMENT,
    )


def run_diff_sizing(
    workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None
) -> bool:
    """Run DreamPlace standalone size-only S50 between placement and CTS."""
    return _run_placement_mode(
        workspace=workspace,
        step=step,
        ecc_module=ecc_module,
        mode=DreamplaceRunMode.DIFF_SIZING,
    )


def _run_placement_mode(
    workspace: Workspace,
    step: EccStep,
    ecc_module: ECCToolsModule | None,
    mode: DreamplaceRunMode,
) -> bool:
    reslut = False

    sub_flow = EccSubFlow(workspace=workspace, workspace_step=step)

    run_stage = (
        EccSubFlowEnum.run_diff_sizing.value
        if mode is DreamplaceRunMode.DIFF_SIZING
        else EccSubFlowEnum.run_placement.value
    )
    backend = _placement_backend(workspace)
    if mode is DreamplaceRunMode.DIFF_SIZING:
        backend = "ecc"
    openroad_backend = mode is DreamplaceRunMode.PLACEMENT and backend == "openroad"
    if not openroad_backend:
        ecc_module = ecc_runner.get_eda_instance(
            workspace=workspace, step=step, ecc_module=ecc_module
        )
        if ecc_module is None:
            return False

    sub_flow.update_step(step_name=EccSubFlowEnum.load_data.value, state=StateEnum.Success)

    dreamplace_module = DreamplaceModule(
        workspace=workspace,
        step=step,
        ecc_module=None if openroad_backend else ecc_module,
        input_def=step.input.def_,
        input_verilog=step.input.verilog,
        output_def=step.output.def_,
        output_verilog=step.output.verilog,
    )
    if mode is DreamplaceRunMode.DIFF_SIZING:
        reslut = dreamplace_module.run_diff_sizing()
    else:
        reslut = dreamplace_module.run_placement()
    if not reslut:
        sub_flow.update_step(
            step_name=run_stage,
            state=StateEnum.Imcomplete,
        )
        return False

    if mode is DreamplaceRunMode.PLACEMENT and (
        openroad_backend or (backend == "ecc" and _is_terminal_placement(workspace, step))
    ):
        # DreamplaceModule already saved DEF and Verilog. A terminal placement
        # must finish before native feature evaluation starts routing analysis.
        sub_flow.update_step(
            step_name=EccSubFlowEnum.run_placement.value,
            state=StateEnum.Success,
            info={
                "backend": backend,
                "placement_only": True,
                "downstream_steps_skipped": ["save data", "analysis"],
            },
        )
        return True

    if backend == "ecc":
        # The placement provider owns its mutated DB. Re-read its committed
        # outputs before feature/save_data so the input DB cannot overwrite them.
        ecc_module.close()
        load_step = replace(
            step,
            input=StepInput(def_=step.output.def_, verilog=step.output.verilog, db=None),
        )
        ecc_module = ecc_runner.create_db_engine(workspace, load_step)
        if ecc_module is None:
            sub_flow.update_step(
                step_name=run_stage,
                state=StateEnum.Imcomplete,
            )
            return False

    ecc_module.feature_placement_map(json_path=step.feature.map)

    sub_flow.update_step(
        step_name=run_stage,
        state=StateEnum.Success,
    )

    reslut = ecc_runner.save_data(
        workspace=workspace, step=step, ecc_module=ecc_module, feature_step=False
    )

    sub_flow.update_step(
        step_name=EccSubFlowEnum.save_data.value,
        state=StateEnum.Success if reslut else StateEnum.Imcomplete,
    )
    if not reslut:
        return False

    if mode is DreamplaceRunMode.PLACEMENT:
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
