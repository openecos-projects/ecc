#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import os
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
               input_def : str,
               input_verilog : str,
               input_db : str | None = None,
               output_def : str | None = None,
               output_verilog : str | None = None,
               output_gds : str | None = None,
               tool : str = "ecc",
               step_directory: str | None = None) -> WorkspaceStep:
    """
    Build the given step in the specified workspace.
    """
    
    step = WorkspaceStep()
    step.name = step_name
    step.tool = tool
    step.version = "0.1"

    # build step directory
    step.directory = step_directory or f"{workspace.directory}/{step.name}_{step.tool}"
    
    # build input paths
    step.input = {
        "def": input_def,
        "verilog": input_verilog,
        "db": input_db
    }  
    
    # build output paths
    if output_def is None:
        output_def = f"{step.directory}/output/{workspace.design.name}_{step.name}.def.gz"
    if output_verilog is None:
        output_verilog = f"{step.directory}/output/{workspace.design.name}_{step.name}.v"
    if output_gds is None:
        output_gds = f"{step.directory}/output/{workspace.design.name}_{step.name}.gds"
    output_db = f"{step.directory}/output/{workspace.design.name}_{step.name}_db"
    output_image = f"{step.directory}/output/{workspace.design.name}_{step.name}.png"
    output_json = f"{step.directory}/output/{workspace.design.name}_{step.name}.json"
    output_view = f"{step.directory}/output/{workspace.design.name}_{step.name}_view"
    output_view_edits = f"{output_view}/edits/layout_edits.json"
    output_lef = f"{step.directory}/output/{workspace.design.name}_{step.name}.lef"
    output_lib = f"{step.directory}/output/{workspace.design.name}_{step.name}.lib"
    output_spef = []
    step.output = {
        "dir": f"{step.directory}/output",
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
    step.data = {
        "dir": f"{step.directory}/data",
        f"{StepEnum.FLOORPLAN.value}": f"{step.directory}/data/fp",
        f"{StepEnum.PNP.value}": f"{step.directory}/data/pnp",
        f"{StepEnum.PLACEMENT.value}": f"{step.directory}/data/pl",
        f"{StepEnum.LEGALIZATION.value}": f"{step.directory}/data/pl",
        f"{StepEnum.FILLER.value}": f"{step.directory}/data/pl",
        f"{StepEnum.CTS.value}": f"{step.directory}/data/cts",
        f"{StepEnum.NETLIST_OPT.value}": f"{step.directory}/data/no",
        f"{StepEnum.TIMING_OPT.value}": f"{step.directory}/data/to",
        f"{StepEnum.TIMING_OPT_DRV.value}": f"{step.directory}/data/to",
        f"{StepEnum.TIMING_OPT_HOLD.value}": f"{step.directory}/data/to",
        f"{StepEnum.TIMING_OPT_SETUP.value}": f"{step.directory}/data/to",
        f"{StepEnum.ROUTING.value}": f"{step.directory}/data/rt",
        f"{StepEnum.STA.value}": f"{step.directory}/data/sta",
        f"{StepEnum.DRC.value}": f"{step.directory}/data/drc",
        f"{StepEnum.RCX.value}": f"{step.directory}/data/rcx"
    }
    
    # build feature paths
    step.feature = {
        "dir": f"{step.directory}/feature",
        "db": f"{step.directory}/feature/{step.name}.db.json",
        "step": f"{step.directory}/feature/{step.name}.step.json",
        "map": f"{step.directory}/feature/{step.name}.map.json",
        "timing": f"{step.directory}/data/sta/{workspace.design.top_module}.rpt.json",
    }
    
    # build report paths
    step.report = {
        "dir": f"{step.directory}/report",
        "db": f"{step.directory}/report/{step.name}.db.rpt",
        "step": f"{step.directory}/report/{step.name}.rpt",
        "sta": {
            "timing": f"{step.directory}/data/sta/{workspace.design.top_module}.rpt",
            "hold": f"{step.directory}/data/sta/{workspace.design.top_module}_hold.skew",
            "setup": f"{step.directory}/data/sta/{workspace.design.top_module}_setup.skew",
            "cap": f"{step.directory}/data/sta/{workspace.design.top_module}.cap",
            "fanout": f"{step.directory}/data/sta/{workspace.design.top_module}.fanout",
            "trans": f"{step.directory}/data/sta/{workspace.design.top_module}.trans",
        },
    }
    
    # build log paths
    step.log = {
        "dir": f"{step.directory}/log",
        "file": f"{step.directory}/log/{step.name}.log"
    }
    
    # build script paths
    step.script = {
        "dir": f"{step.directory}/script",
        "main": f"{step.directory}/script/{step.name}_main.tcl"
    }
    
    # build analysis paths
    step.analysis = {
        "dir": f"{step.directory}/analysis",
        "metrics": f"{step.directory}/analysis/{step.name}_metrics.json",
        "statis_csv": f"{step.directory}/analysis/{step.name}_statis.csv"
    }    
    
    # build sub flow paths
    step.subflow = {
        "path": f"{step.directory}/subflow.json",
        "steps": []
    }  
    
    # build checklist paths and data
    step.checklist = {
        "path": f"{step.directory}/checklist.json",
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
    import os
    
    os.makedirs(step.directory, exist_ok=True)
    os.makedirs(step.output.get("dir", f"{step.directory}/output"), exist_ok=True)
    os.makedirs(step.data.get("dir", f"{step.directory}/data"), exist_ok=True)
    os.makedirs(step.feature.get("dir", f"{step.directory}/feature"), exist_ok=True)
    os.makedirs(step.report.get("dir", f"{step.directory}/report"), exist_ok=True)
    os.makedirs(step.log.get("dir", f"{step.directory}/log"), exist_ok=True)
    os.makedirs(step.script.get("dir", f"{step.directory}/script"), exist_ok=True)
    os.makedirs(step.analysis.get("dir", f"{step.directory}/analysis"), exist_ok=True)
    
    # build data directory
    for key, dir in step.data.items():
        os.makedirs(dir, exist_ok=True)
        
    # create pl sub dir
    os.makedirs(f"{step.directory}/data/pl/density", exist_ok=True)
    os.makedirs(f"{step.directory}/data/pl/gui", exist_ok=True)
    os.makedirs(f"{step.directory}/data/pl/log", exist_ok=True)
    os.makedirs(f"{step.directory}/data/pl/plot", exist_ok=True)
    os.makedirs(f"{step.directory}/data/pl/report", exist_ok=True)  
        

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
