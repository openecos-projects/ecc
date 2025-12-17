#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from chipcompiler.workspaces import WorkspaceStep, Workspace

def is_eda_exist() -> bool:
    """
    Check if the iEDA tool is installed and accessible.
    """
    import sys
    import os
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    ieda_bin_dir = os.path.abspath(os.path.join(current_dir, '../../thirdparty/iEDA/bin'))
    sys.path.insert(0, ieda_bin_dir)
    
    try:
        import ieda_py
        return True
    except ImportError:
        return False

def build_step(workspace: Workspace, 
               step_name: str,
               input_def : str,
               input_verilog : str,
               output_def : str = None,
               output_verilog : str = None,
               output_gds : str = None) -> WorkspaceStep:
    """
    Build the given step in the specified workspace.
    """
    
    step = WorkspaceStep()
    step.name = step_name
    step.tool = "iEDA"
    step.version = "0.1"

    # build step directory
    step.directory = f"{workspace.directory}/{step.name}_{step.tool.lower()}"
    
    # build config paths    
    step.config = {
        'dir': f"{step.directory}/config",
        "cts": f"{step.directory}/config/cts_default_config.json",
        "db": f"{step.directory}/config/db_default_config.json",
        "drc": f"{step.directory}/config/drc_default_config.json",
        "flow": f"{step.directory}/config/flow_config.json",
        "fp": f"{step.directory}/config/fp_default_config.json",
        "fixfanout": f"{step.directory}/config/no_default_config_fixfanout.json",
        "place": f"{step.directory}/config/pl_default_config.json",
        "pnp": f"{step.directory}/config/pnp_default_config.json",
        "route": f"{step.directory}/config/rt_default_config.json",
        "drv": f"{step.directory}/config/to_default_config_drv.json",
        "hold": f"{step.directory}/config/to_default_config_hold.json",
        "setup": "{step.directory}/config/to_default_config_setup.json"
    }
    
    # build input paths
    step.input = {
        "def": input_def,
        "verilog": input_verilog
    }  
    
    # build output paths
    if output_def is None:
        output_def = f"{step.directory}/output/{workspace.design.name}_{step.name}.def.gz"
    if output_verilog is None:
        output_verilog = f"{step.directory}/output/{workspace.design.name}_{step.name}.v"
    if output_gds is None:
        output_gds = f"{step.directory}/output/{workspace.design.name}_{step.name}.gds"
    step.output = {
        "dir": f"{step.directory}/output",
        "def": output_def,
        "verilog": output_verilog,
        "gds": output_gds
    }
    
    # build data paths
    step.data = {
        "dir": f"{step.directory}/data"
    }
    
    # build feature paths
    step.feature = {
        "dir": f"{step.directory}/feature",
        "db": f"{step.directory}/feature/{step.name}.db.json",
        "step": f"{step.directory}/feature/{step.name}.step.json"
    }
    
    # build report paths
    step.report = {
        "dir": f"{step.directory}/report",
        "summary": f"{step.directory}/report/{step.name}.summary.rpt",
        "drc": f"{step.directory}/report/{step.name}_drc.rpt"
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
        "dir": f"{step.directory}/analysis"
    }    
    
    return step

def build_step_space(step: WorkspaceStep) -> None:
    """
    Create the workspace directories for the given step.
    """
    import os
    
    os.makedirs(step.directory, exist_ok=True)
    os.makedirs(step.config.get("dir", f"{step.directory}/config"), exist_ok=True)
    os.makedirs(step.output.get("dir", f"{step.directory}/output"), exist_ok=True)
    os.makedirs(step.data.get("dir", f"{step.directory}/data"), exist_ok=True)
    os.makedirs(step.feature.get("dir", f"{step.directory}/feature"), exist_ok=True)
    os.makedirs(step.report.get("dir", f"{step.directory}/report"), exist_ok=True)
    os.makedirs(step.log.get("dir", f"{step.directory}/log"), exist_ok=True)
    os.makedirs(step.script.get("dir", f"{step.directory}/script"), exist_ok=True)
    os.makedirs(step.analysis.get("dir", f"{step.directory}/analysis"), exist_ok=True)
