#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from pathlib import Path

from chipcompiler.data import (
    WorkspaceStep,
    Workspace,
    Parameters,
    StepEnum,
    StateEnum,
    build_workspace_config_paths,
    update_step_config,
)

def build_step(workspace: Workspace,
               step_name: str,
               input_def : Path | None,
               input_verilog : Path | None,
               input_db : Path | None = None,
               output_def : Path | None = None,
               output_verilog : Path | None = None,
               output_gds : Path | None = None,
               tool : str = "ecc",
               step_directory: Path | None = None) -> WorkspaceStep:
    """
    Build the given step in the specified workspace.
    """
    
    step = WorkspaceStep()
    step.name = step_name
    step.tool = tool
    step.version = "0.1"

    # build step directory
    step.directory = (
        Path(step_directory)
        if step_directory
        else Path(workspace.directory) / f"{step.name}_{step.tool}"
    )
    
    # build input paths
    step.input = {
        "def": Path(input_def) if input_def else None,
        "verilog": Path(input_verilog) if input_verilog else None,
        "db": Path(input_db) if input_db else None
    }  
    
    # build output paths
    output_dir = step.directory / "output"
    if output_def is None:
        output_def = output_dir / f"{workspace.design.name}_{step.name}.def.gz"
    else:
        output_def = Path(output_def)
    if output_verilog is None:
        output_verilog = output_dir / f"{workspace.design.name}_{step.name}.v.gz"
    else:
        output_verilog = Path(output_verilog)
    if output_gds is None:
        output_gds = output_dir / f"{workspace.design.name}_{step.name}.gds"
    else:
        output_gds = Path(output_gds)
    output_db = output_dir / f"{workspace.design.name}_{step.name}_db"
    output_image = output_dir / f"{workspace.design.name}_{step.name}.png"
    output_json = output_dir / f"{workspace.design.name}_{step.name}.json"
    output_view = output_dir / f"{workspace.design.name}_{step.name}_view"
    output_view_edits = output_view / "edits" / "layout_edits.json"
    output_lef = output_dir / f"{workspace.design.name}_{step.name}.lef"
    output_lib = output_dir / f"{workspace.design.name}_{step.name}.lib"
    output_spef = []
    step.output = {
        "dir": output_dir,
        "def": output_def,
        "verilog": output_verilog,
        "gds": output_gds,
        "db": output_db,
        "image": output_image,
        "json" : output_json,
        "view_json" : output_view,
        "view_json_edits" : output_view_edits,
        "lef" : output_lef,
        "lib" : output_lib,
        "spef" : output_spef
    }
    
    # build data paths
    data_dir = step.directory / "data"
    step.data = {
        "dir": data_dir,
        f"{StepEnum.FLOORPLAN.value}": data_dir / "fp",
        f"{StepEnum.PNP.value}": data_dir / "pnp",
        f"{StepEnum.PLACEMENT.value}": data_dir / "pl",
        f"{StepEnum.LEGALIZATION.value}": data_dir / "pl",
        f"{StepEnum.FILLER.value}": data_dir / "pl",
        f"{StepEnum.CTS.value}": data_dir / "cts",
        f"{StepEnum.NETLIST_OPT.value}": data_dir / "no",
        f"{StepEnum.TIMING_OPT.value}": data_dir / "to",
        f"{StepEnum.TIMING_OPT_DRV.value}": data_dir / "to",
        f"{StepEnum.TIMING_OPT_HOLD.value}": data_dir / "to",
        f"{StepEnum.TIMING_OPT_SETUP.value}": data_dir / "to",
        f"{StepEnum.ROUTING.value}": data_dir / "rt",
        f"{StepEnum.STA.value}": data_dir / "sta",
        f"{StepEnum.DRC.value}": data_dir / "drc",
        f"{StepEnum.RCX.value}": data_dir / "rcx"
    }
    
    # build feature paths
    feature_dir = step.directory / "feature"
    step.feature = {
        "dir": feature_dir,
        "db": feature_dir / f"{step.name}.db.json",
        "step": feature_dir / f"{step.name}.step.json",
        "map": feature_dir / f"{step.name}.map.json",
        "sta": {
            "dir": feature_dir,
            "qor_summary_root": feature_dir,
            "timing_paths_root": feature_dir,
        },
    }
    
    # build report paths
    report_dir = step.directory / "report"
    step.report = {
        "dir": report_dir,
        "db": report_dir / f"{step.name}.db.rpt",
        "step": report_dir / f"{step.name}.rpt",
        "sta": {
            "dir": report_dir,
        },
    }
    
    # build log paths
    log_dir = step.directory / "log"
    step.log = {
        "dir": log_dir,
        "file": log_dir / f"{step.name}.log"
    }
    
    # build script paths
    script_dir = step.directory / "script"
    step.script = {
        "dir": script_dir,
        "main": script_dir / f"{step.name}_main.tcl"
    }
    
    # build analysis paths
    analysis_dir = step.directory / "analysis"
    qor_metrics_path = analysis_dir / "qor_metrics.json"
    step.analysis = {
        "dir": analysis_dir,
        "metrics": qor_metrics_path,
        "qor_metrics": qor_metrics_path,
        "qor_summary": analysis_dir / "qor_summary.json",
        "qor_hotspots": analysis_dir / "qor_hotspots.json",
        "sta_timing_issues": analysis_dir / "sta_timing_issues.json",
        "statis_csv": analysis_dir / f"{step.name}_statis.csv"
    }    
    
    # build sub flow paths
    step.subflow = {
        "path": step.directory / "subflow.json",
        "steps": []
    }  
    
    # build checklist paths and data
    step.checklist = {
        "path": step.directory / "checklist.json",
        "checklist": []
    }
    
    return step

def build_sub_flow(workspace : Workspace,
                   workspace_step : WorkspaceStep):
    from .subflow import EccSubFlow
    subflow = EccSubFlow(workspace=workspace,
                         workspace_step=workspace_step)
    
    subflow.build_sub_flow()    
    
def build_checklist(workspace : Workspace,
                    workspace_step : WorkspaceStep):
    from .checklist import EccChecklist
    checklist = EccChecklist(workspace=workspace,
                           workspace_step=workspace_step)
    
    checklist.build_checklist() 

def build_step_space(step: WorkspaceStep) -> None:
    """
    Create the workspace directories for the given step.
    """
    step_directory = Path(step.directory)
    
    step_directory.mkdir(parents=True, exist_ok=True)
    Path(step.output.get("dir", step_directory / "output")).mkdir(parents=True, exist_ok=True)
    Path(step.data.get("dir", step_directory / "data")).mkdir(parents=True, exist_ok=True)
    Path(step.feature.get("dir", step_directory / "feature")).mkdir(parents=True, exist_ok=True)
    Path(step.report.get("dir", step_directory / "report")).mkdir(parents=True, exist_ok=True)
    Path(step.log.get("dir", step_directory / "log")).mkdir(parents=True, exist_ok=True)
    Path(step.script.get("dir", step_directory / "script")).mkdir(parents=True, exist_ok=True)
    Path(step.analysis.get("dir", step_directory / "analysis")).mkdir(parents=True, exist_ok=True)
    
    # build data directory
    for directory in step.data.values():
        Path(directory).mkdir(parents=True, exist_ok=True)
        
    # create pl sub dir
    (step_directory / "data" / "pl" / "density").mkdir(parents=True, exist_ok=True)
    (step_directory / "data" / "pl" / "gui").mkdir(parents=True, exist_ok=True)
    (step_directory / "data" / "pl" / "log").mkdir(parents=True, exist_ok=True)
    (step_directory / "data" / "pl" / "plot").mkdir(parents=True, exist_ok=True)
    (step_directory / "data" / "pl" / "report").mkdir(parents=True, exist_ok=True)
        

def build_step_config(workspace: Workspace,
                      step: WorkspaceStep):
    """
    Build the configuration files for the given step based on the parameters.
    """
    # build subflow json
    build_sub_flow(workspace=workspace,
                   workspace_step=step)
    
    build_checklist(workspace=workspace,
                    workspace_step=step)

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
        step.output["spef"] = [
            spef_path
            for corner in rcx_config.get("corners", [])
            for spef_item in (
                corner.get("spef_file", [])
                if isinstance(corner.get("spef_file", []), list)
                else [corner.get("spef_file", "")]
            )
            for spef_path in (
                spef_item.values()
                if isinstance(spef_item, dict)
                else [spef_item]
            )
            if spef_path
        ]
