#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import os
import stat
from chipcompiler.data import WorkspaceStep, Workspace, Parameters, StepEnum, StateEnum

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
    step.tool = "ecc"
    step.version = "0.1"

    # build step directory
    step.directory = f"{workspace.directory}/{step.name}_{step.tool}"
    
    # build config paths    
    step.config = {
        "dir": f"{step.directory}/config",
        "flow": f"{step.directory}/config/flow_config.json",
        "db": f"{step.directory}/config/db_default_config.json",
        f"{StepEnum.CTS.value}": f"{step.directory}/config/cts_default_config.json",
        f"{StepEnum.DRC.value}": f"{step.directory}/config/drc_default_config.json",
        f"{StepEnum.FLOORPLAN.value}": f"{step.directory}/config/fp_default_config.json",
        f"{StepEnum.NETLIST_OPT.value}": f"{step.directory}/config/no_default_config_fixfanout.json",
        f"{StepEnum.PLACEMENT.value}": f"{step.directory}/config/pl_default_config.json",
        f"{StepEnum.PNP.value}": f"{step.directory}/config/pnp_default_config.json",
        f"{StepEnum.ROUTING.value}": f"{step.directory}/config/rt_default_config.json",
        f"{StepEnum.TIMING_OPT_DRV.value}": f"{step.directory}/config/to_default_config_drv.json",
        f"{StepEnum.TIMING_OPT_HOLD.value}": f"{step.directory}/config/to_default_config_hold.json",
        f"{StepEnum.TIMING_OPT_SETUP.value}": f"{step.directory}/config/to_default_config_setup.json",
        f"{StepEnum.LEGALIZATION.value}": f"{step.directory}/config/pl_default_config.json",
        f"{StepEnum.FILLER.value}": f"{step.directory}/config/pl_default_config.json"
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
    output_image = f"{step.directory}/output/{workspace.design.name}_{step.name}.png"
    step.output = {
        "dir": f"{step.directory}/output",
        "def": output_def,
        "verilog": output_verilog,
        "gds": output_gds,
        "image": output_image
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
        f"{StepEnum.TIMING_OPT_DRV.value}": f"{step.directory}/data/to",
        f"{StepEnum.TIMING_OPT_HOLD.value}": f"{step.directory}/data/to",
        f"{StepEnum.TIMING_OPT_SETUP.value}": f"{step.directory}/data/to",
        f"{StepEnum.ROUTING.value}": f"{step.directory}/data/rt",
        f"{StepEnum.STA.value}": f"{step.directory}/data/sta",
        f"{StepEnum.DRC.value}": f"{step.directory}/data/drc"
    }
    
    # build feature paths
    step.feature = {
        "dir": f"{step.directory}/feature",
        "db": f"{step.directory}/feature/{step.name}.db.json",
        "step": f"{step.directory}/feature/{step.name}.step.json",
        "map": f"{step.directory}/feature/{step.name}.map.json",
    }
    
    # build report paths
    step.report = {
        "dir": f"{step.directory}/report",
        "db": f"{step.directory}/report/{step.name}.db.rpt",
        "step": f"{step.directory}/report/{step.name}.rpt"
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
    os.makedirs(step.config.get("dir", f"{step.directory}/config"), exist_ok=True)
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
    
    # update config by parameters
    from chipcompiler.utility import json_read, json_write

    def _ensure_writable(path: str):
        """Make files writable after copying from read-only sources."""
        for root, dirs, files in os.walk(path):
            for name in dirs + files:
                target = os.path.join(root, name)
                try:
                    os.chmod(target, os.stat(target).st_mode | stat.S_IWUSR)
                except OSError:
                    pass
    
    def _update_flow():
        # read config
        config = json_read(step.config["flow"])
        
        # parameters
        config["ConfigPath"]["idb_path"] = step.config["db"]
        config["ConfigPath"]["ifp_path"] = step.config[f"{StepEnum.FLOORPLAN.value}"]
        config["ConfigPath"]["ipl_path"] = step.config[f"{StepEnum.PLACEMENT.value}"]
        config["ConfigPath"]["irt_path"] = step.config[f"{StepEnum.ROUTING.value}"]
        config["ConfigPath"]["idrc_path"] = step.config[f"{StepEnum.DRC.value}"]
        config["ConfigPath"]["icts_path"] = step.config[f"{StepEnum.CTS.value}"]
        config["ConfigPath"]["ito_path"] = step.config[f"{StepEnum.TIMING_OPT_DRV.value}"]
        config["ConfigPath"]["ipnp_path"] = step.config[f"{StepEnum.PNP.value}"]
        
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
        config["LayerSettings"]["routing_layer_1st"] = workspace.parameters.data.get("Bottom layer", "")
        
        # write back
        json_write(step.config["db"], config)
    
    def _update_fixfanout():
        # read config
        config = json_read(step.config[f"{StepEnum.NETLIST_OPT.value}"])
        
        # parameters
        if len(workspace.pdk.buffers) > 0:
            config["insert_buffer"] = workspace.pdk.buffers[0]
        else:
            config["insert_buffer"] = ""
        
        config["max_fanout"] = workspace.parameters.data.get("Max fanout", 32)
        
        # write back
        json_write(step.config[f"{StepEnum.NETLIST_OPT.value}"], config)
        
    def _update_placement():
        # read config
        config = json_read(step.config[f"{StepEnum.PLACEMENT.value}"])
        
        # parameters
        config["PL"]["BUFFER"]["buffer_type"] = workspace.pdk.buffers
        config["PL"]["Filler"]["first_iter"] = workspace.pdk.fillers
        config["PL"]["Filler"]["second_iter"] = workspace.pdk.fillers
        
        # write back
        json_write(step.config[f"{StepEnum.PLACEMENT.value}"], config)
        
    def _update_cts():
        # read config
        config = json_read(step.config[f"{StepEnum.CTS.value}"])
        
        # parameters
        if len(workspace.pdk.buffers) > 0:
            config["root_buffer_type"] = workspace.pdk.buffers[0]
        else:
            config["root_buffer_type"] = ""
        
        config["buffer_type"] = workspace.pdk.buffers
        
        # write back
        json_write(step.config[f"{StepEnum.CTS.value}"], config)
        
    def _update_drv():
        # read config
        config = json_read(step.config[f"{StepEnum.TIMING_OPT_DRV.value}"])
        
        # parameters
        config["DRV_insert_buffers"] = workspace.pdk.buffers
        
        # write back
        json_write(step.config[f"{StepEnum.TIMING_OPT_DRV.value}"], config)
        
    def _update_hold():
        # read config
        config = json_read(step.config[f"{StepEnum.TIMING_OPT_HOLD.value}"])
        
        # parameters
        config["hold_insert_buffers"] = workspace.pdk.buffers
        
        # write back
        json_write(step.config[f"{StepEnum.TIMING_OPT_HOLD.value}"], config)
        
    def _update_setup():
        # read config
        config = json_read(step.config[f"{StepEnum.TIMING_OPT_SETUP.value}"])
        
        # parameters
        config["setup_insert_buffers"] = workspace.pdk.buffers
        
        # write back
        json_write(step.config[f"{StepEnum.TIMING_OPT_SETUP.value}"], config)
        
    def _update_router():
        # read config
        config = json_read(step.config[f"{StepEnum.ROUTING.value}"])
        
        # parameters
        config["RT"]["-temp_directory_path"] = step.data.get(f"{StepEnum.ROUTING.value}", "")
        config["RT"]["-bottom_routing_layer"] = workspace.parameters.data.get("Bottom layer", "")
        config["RT"]["-top_routing_layer"] = workspace.parameters.data.get("Top layer", "")
        
        # write back
        json_write(step.config[f"{StepEnum.ROUTING.value}"], config)
        
    # copy files to origin folder
    import shutil
    current_dir = os.path.dirname(os.path.abspath(__file__))
    default_dir = os.path.abspath(os.path.join(current_dir, 'configs'))
    shutil.copytree(default_dir, step.config["dir"], dirs_exist_ok=True)
    _ensure_writable(step.config["dir"])
    
    _update_flow()    
    _update_db()
    _update_fixfanout()
    _update_placement()
    _update_cts()
    _update_drv()
    _update_hold()
    _update_setup()
    _update_router()
