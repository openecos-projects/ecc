#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import os
from chipcompiler.workspaces import WorkspaceStep, Workspace, Parameters

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
        "setup": f"{step.directory}/config/to_default_config_setup.json"
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
        "db": f"{step.directory}/report/{step.name}.db.json",
        "step": f"{step.directory}/report/{step.name}.step.json"
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

def build_step_config(workspace: Workspace,
                      step: WorkspaceStep, 
                      parameters: Parameters):
    """
    Build the configuration files for the given step based on the parameters.
    """
    # update config by parameters
    from chipcompiler.utility import json_read, json_write
    
    def _update_flow():
        # read config
        config = json_read(step.config["flow"])
        
        # parameters
        config["ConfigPath"]["idb_path"] = step.config["db"]
        config["ConfigPath"]["ifp_path"] = step.config["fp"]
        config["ConfigPath"]["ipl_path"] = step.config["place"]
        config["ConfigPath"]["irt_path"] = step.config["route"]
        config["ConfigPath"]["idrc_path"] = step.config["drc"]
        config["ConfigPath"]["icts_path"] = step.config["cts"]
        config["ConfigPath"]["ito_path"] = step.config["drv"]
        config["ConfigPath"]["ipnp_path"] = step.config["pnp"]
        
        # write back
        json_write(step.config["flow"], config)
        
    def _update_db():
        # read config
        config = json_read(step.config["db"])
        
        # parameters
        config["INPUT"]["tech_lef_path"] = workspace.pdk.tech
        config["INPUT"]["lef_paths"] = workspace.pdk.lefs
        config["INPUT"]["lib_path"] = workspace.pdk.libs
        config["INPUT"]["sdc_path"] = workspace.pdk.sdc
        config["INPUT"]["spef"] = workspace.pdk.spef
        config["INPUT"]["def_path"] = step.input["def"]
        config["INPUT"]["verilog_path"] = step.input["verilog"]
        config["OUTPUT"]["output_dir_path"] = step.output["dir"]
        config["LayerSettings"]["routing_layer_1st"] = parameters.data.get("Bottom layer", "")
        
        # write back
        json_write(step.config["db"], config)
    
    def _update_fixfanout():
        # read config
        config = json_read(step.config["fixfanout"])
        
        # parameters
        buffers = parameters.data.get("Buffers", [])
        if len(buffers) > 0:
            config["insert_buffer"] = buffers[0]
        else:
            config["insert_buffer"] = ""
        
        config["max_fanout"] = parameters.data.get("Max fanout", 32)
        
        # write back
        json_write(step.config["fixfanout"], config)
        
    def _update_placement():
        # read config
        config = json_read(step.config["place"])
        
        # parameters
        config["PL"]["BUFFER"]["buffer_type"] = parameters.data.get("Buffers", [])
        config["PL"]["Filler"]["first_iter"] = parameters.data.get("Fillers", [])
        config["PL"]["Filler"]["second_iter"] = parameters.data.get("Fillers", [])
        
        # write back
        json_write(step.config["place"], config)
        
    def _update_cts():
        # read config
        config = json_read(step.config["cts"])
        
        # parameters
        buffers = parameters.data.get("Buffers", [])
        if len(buffers) > 0:
            config["root_buffer_type"] = buffers[0]
        else:
            config["root_buffer_type"] = ""
        
        config["buffer_type"] = parameters.data.get("Buffers", [])
        
        # write back
        json_write(step.config["cts"], config)
        
    def _update_drv():
        # read config
        config = json_read(step.config["drv"])
        
        # parameters
        config["DRV_insert_buffers"] = parameters.data.get("Buffers", [])
        
        # write back
        json_write(step.config["drv"], config)
        
    def _update_hold():
        # read config
        config = json_read(step.config["hold"])
        
        # parameters
        config["hold_insert_buffers"] = parameters.data.get("Buffers", [])
        
        # write back
        json_write(step.config["hold"], config)
        
    def _update_setup():
        # read config
        config = json_read(step.config["setup"])
        
        # parameters
        config["setup_insert_buffers"] = parameters.data.get("Buffers", [])
        
        # write back
        json_write(step.config["setup"], config)
        
    def _update_router():
        # read config
        config = json_read(step.config["route"])
        
        # parameters
        config["RT"]["-bottom_routing_layer"] = parameters.data.get("Bottom layer", "")
        config["RT"]["-top_routing_layer"] = parameters.data.get("Top layer", "")
        
        # write back
        json_write(step.config["route"], config)
        
    # copy files to origin folder
    import shutil
    # Get the directory of the current script
    current_dir = os.path.dirname(os.path.abspath(__file__))
    default_dir = os.path.abspath(os.path.join(current_dir, 'configs'))
    shutil.copytree(default_dir, step.config["dir"], dirs_exist_ok=True)
    
    _update_flow()    
    _update_db()
    _update_fixfanout()
    _update_placement()
    _update_cts()
    _update_drv()
    _update_hold()
    _update_setup()
    _update_router()