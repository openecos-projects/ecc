#!/usr/bin/env python
from pathlib import Path

from chipcompiler.data import (
    ChecklistState,
    EccAnalysis,
    EccData,
    EccFeature,
    EccOutput,
    EccReport,
    EccScript,
    EccStep,
    LogPaths,
    StaReportPaths,
    StepEnum,
    StepInput,
    SubflowState,
    Workspace,
    WorkspaceStep,
    build_workspace_config_paths,
    update_step_config,
)


def build_step(
    workspace: Workspace,
    step_name: str,
    input_def: Path | None,
    input_verilog: Path | None,
    input_db: Path | str | None = None,
    output_def: Path | None = None,
    output_verilog: Path | None = None,
    output_gds: Path | None = None,
    tool: str = "ecc",
    step_directory: Path | None = None,
) -> EccStep:
    """
    Build the given step in the specified workspace.
    """

    directory = (
        Path(step_directory)
        if step_directory
        else Path(workspace.directory) / f"{step_name}_{tool}"
    )
    design = workspace.design.name
    top_module = workspace.design.top_module
    output_dir = directory / "output"
    data_dir = directory / "data"
    sta_dir = data_dir / "sta"
    feature_dir = directory / "feature"
    report_dir = directory / "report"
    output_view = output_dir / f"{design}_{step_name}_view"

    return EccStep(
        name=step_name,
        tool=tool,
        version="0.1",
        directory=directory,
        input=StepInput(
            def_=Path(input_def) if input_def else None,
            verilog=Path(input_verilog) if input_verilog else None,
            db=Path(input_db) if input_db else None,
        ),
        output=EccOutput(
            dir=output_dir,
            def_=Path(output_def) if output_def else output_dir / f"{design}_{step_name}.def.gz",
            verilog=(
                Path(output_verilog)
                if output_verilog
                else output_dir / f"{design}_{step_name}.v.gz"
            ),
            gds=Path(output_gds) if output_gds else output_dir / f"{design}_{step_name}.gds",
            db=output_dir / f"{design}_{step_name}_db",
            image=output_dir / f"{design}_{step_name}.png",
            json=output_dir / f"{design}_{step_name}.json",
            view_json=output_view,
            view_json_edits=output_view / "edits" / "layout_edits.json",
            lef=output_dir / f"{design}_{step_name}.lef",
            lib=output_dir / f"{design}_{step_name}.lib",
            spef=[],
        ),
        data=EccData(
            dir=data_dir,
            steps={
                StepEnum.FLOORPLAN.value: data_dir / "fp",
                StepEnum.PNP.value: data_dir / "pnp",
                StepEnum.PLACEMENT.value: data_dir / "pl",
                StepEnum.LEGALIZATION.value: data_dir / "pl",
                StepEnum.FILLER.value: data_dir / "pl",
                StepEnum.CTS.value: data_dir / "cts",
                StepEnum.NETLIST_OPT.value: data_dir / "no",
                StepEnum.TIMING_OPT.value: data_dir / "to",
                StepEnum.TIMING_OPT_DRV.value: data_dir / "to",
                StepEnum.TIMING_OPT_HOLD.value: data_dir / "to",
                StepEnum.TIMING_OPT_SETUP.value: data_dir / "to",
                StepEnum.ROUTING.value: data_dir / "rt",
                StepEnum.STA.value: sta_dir,
                StepEnum.DRC.value: data_dir / "drc",
                StepEnum.RCX.value: data_dir / "rcx",
            },
        ),
        feature=EccFeature(
            dir=feature_dir,
            db=feature_dir / f"{step_name}.db.json",
            step=feature_dir / f"{step_name}.step.json",
            map=feature_dir / f"{step_name}.map.json",
            timing=sta_dir / f"{top_module}.rpt.json",
        ),
        report=EccReport(
            dir=report_dir,
            db=report_dir / f"{step_name}.db.rpt",
            step=report_dir / f"{step_name}.rpt",
            sta=StaReportPaths(
                timing=sta_dir / f"{top_module}.rpt",
                hold=sta_dir / f"{top_module}_hold.skew",
                setup=sta_dir / f"{top_module}_setup.skew",
                cap=sta_dir / f"{top_module}.cap",
                fanout=sta_dir / f"{top_module}.fanout",
                trans=sta_dir / f"{top_module}.trans",
            ),
        ),
        log=LogPaths(
            dir=directory / "log",
            file=directory / "log" / f"{step_name}.log",
        ),
        script=EccScript(
            dir=directory / "script",
            main=directory / "script" / f"{step_name}_main.tcl",
        ),
        analysis=EccAnalysis(
            dir=directory / "analysis",
            metrics=directory / "analysis" / f"{step_name}_metrics.json",
            statis_csv=directory / "analysis" / f"{step_name}_statis.csv",
        ),
        subflow=SubflowState(path=directory / "subflow.json", steps=[]),
        checklist=ChecklistState(path=directory / "checklist.json", checklist=[]),
    )


def build_sub_flow(workspace: Workspace, workspace_step: WorkspaceStep):
    from .subflow import EccSubFlow

    subflow = EccSubFlow(workspace=workspace, workspace_step=workspace_step)

    subflow.build_sub_flow()


def build_checklist(workspace: Workspace, workspace_step: EccStep):
    from .checklist import EccChecklist

    checklist = EccChecklist(workspace=workspace, workspace_step=workspace_step)

    checklist.build_checklist()


def build_step_space(step: WorkspaceStep) -> None:
    """
    Create the workspace directories for the given step.
    """
    step_directory = Path(step.directory)

    step_directory.mkdir(parents=True, exist_ok=True)
    Path(step.output.dir or step_directory / "output").mkdir(parents=True, exist_ok=True)
    Path(step.data.dir or step_directory / "data").mkdir(parents=True, exist_ok=True)
    Path(step.feature.dir or step_directory / "feature").mkdir(parents=True, exist_ok=True)
    Path(step.report.dir or step_directory / "report").mkdir(parents=True, exist_ok=True)
    Path(step.log.dir or step_directory / "log").mkdir(parents=True, exist_ok=True)
    Path(step.script.dir or step_directory / "script").mkdir(parents=True, exist_ok=True)
    Path(step.analysis.dir or step_directory / "analysis").mkdir(parents=True, exist_ok=True)

    # build data directory
    for directory in step.data.iter_directories():
        Path(directory).mkdir(parents=True, exist_ok=True)

    # create pl sub dir
    (step_directory / "data" / "pl" / "density").mkdir(parents=True, exist_ok=True)
    (step_directory / "data" / "pl" / "gui").mkdir(parents=True, exist_ok=True)
    (step_directory / "data" / "pl" / "log").mkdir(parents=True, exist_ok=True)
    (step_directory / "data" / "pl" / "plot").mkdir(parents=True, exist_ok=True)
    (step_directory / "data" / "pl" / "report").mkdir(parents=True, exist_ok=True)


def build_step_config(workspace: Workspace, step: EccStep):
    """
    Build the configuration files for the given step based on the parameters.
    """
    # build subflow json
    build_sub_flow(workspace=workspace, workspace_step=step)

    build_checklist(workspace=workspace, workspace_step=step)

    if not workspace.config:
        workspace.config = build_workspace_config_paths(workspace)

    # reload parameters
    from chipcompiler.data import load_parameter

    parameter = load_parameter(workspace.parameters.path)
    workspace.parameters = parameter

    update_step_config(workspace=workspace, step=step)

    if step.name == StepEnum.RCX.value:
        from chipcompiler.utility import json_read

        rcx_config = json_read(workspace.config[f"{StepEnum.RCX.value}"])
        step.output.spef = [
            spef_path
            for corner in rcx_config.get("corners", [])
            for spef_item in (
                corner.get("spef_file", [])
                if isinstance(corner.get("spef_file", []), list)
                else [corner.get("spef_file", "")]
            )
            for spef_path in (spef_item.values() if isinstance(spef_item, dict) else [spef_item])
            if spef_path
        ]
