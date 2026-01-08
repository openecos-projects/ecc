#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from dataclasses import dataclass, field
from .parameter import Parameters, save_parameter
from chipcompiler.utility import Logger, create_logger, dict_to_str
    
@dataclass
class PDK:
    """
    Dataclass for PDK information
    """
    name : str = "" # pdk name
    version : str = "" # pdk version
    tech : str = "" # pdk tech lef file
    lefs : list = field(default_factory=list) # pdk lef files
    libs : list = field(default_factory=list) # pdk liberty files
    sdc : str = "" # pdk sdc file
    spef : str = "" # pdk spef file
    site_core : str = "" # core site
    site_io : str = "" # io site
    site_corner : str = "" # corner site
    tap_cell : str = "" # tap cell
    end_cap : str = "" # end cap
    buffers : list = field(default_factory=list) # buffers
    fillers : list = field(default_factory=list) # fillers
    tie_high_cell : str = ""
    tie_high_port : str = ""
    tie_low_cell : str = ""
    tie_low_port : str = ""
    dont_use : list = field(default_factory=list) # don't use cell list
    

@dataclass
class OriginDesign:
    """
    Dataclass for original design information
    """
    name : str = "" # design name
    top_module : str = "" # top module name
    origin_def : str = "" # original def file path
    origin_verilog : str = "" # original verilog file path
    input_filelist : str = "" # input filelist for synthesis
    
@dataclass
class Flow:
    """
    Dataclass for design flow
    """
    path : str = "" # flow file path
    data : dict = field(default_factory=dict) # flow steps
    
@dataclass
class Workspace:
    """
    Dataclass for workspace information
    """
    directory : str = "" # workspace directory
    design : OriginDesign = field(default_factory=OriginDesign) # original design info
    pdk : PDK = field(default_factory=PDK) # pdk information
    parameters : Parameters = field(default_factory=Parameters) # design parameters
    flow : Flow = field(default_factory=Flow) # design flow for this workspace
    
    # logger
    logger : Logger = field(default_factory=Logger) # logger for this workspace
    
@dataclass
class WorkspaceStep:
    """
    Dataclass for workspace step path information, describe all the info for this task step.
    """
    # step basic info
    name : str = "" # step name
    directory : str = "" # step working directory
    
    # eda tool info
    tool : str = "" # eda tool name
    version : str = "" # eda tool version
    
    # Paths for this step
    config : dict = field(default_factory=dict) # config path about this step
    input : dict = field(default_factory=dict) # input path about this step
    output : dict = field(default_factory=dict) # output path about this step
    data : dict = field(default_factory=dict) # data path about this step
    feature : dict = field(default_factory=dict) # features path about this step
    report : dict = field(default_factory=dict) # report path about this step
    log : dict = field(default_factory=dict) # log path about this step
    script : dict = field(default_factory=dict) # script path about this step
    analysis : dict = field(default_factory=dict) # analysis path about this step
    
    # step result info
    result : dict = field(default_factory=dict) # result info about this step

def create_workspace(directory : str,
                     origin_def : str,
                     origin_verilog : str,
                     pdk : PDK,
                     parameters : Parameters,
                     input_filelist : str = "") -> Workspace:
    """
    Create a workspace for chip design flow.

    Args:
        directory: Workspace directory path
        origin_def: Original DEF file path (for physical design)
        origin_verilog: Original verilog file path (RTL or synthesized netlist)
        pdk: PDK information (LEF, Liberty, SDC, etc.)
        parameters: Design parameters (clock, frequency, etc.)
        input_filelist: Optional filelist for synthesis (SystemVerilog sources)

    Returns:
        Workspace instance with all paths configured

    Note:
        - origin_verilog can be either RTL (requires SYNTHESIS step) or
          pre-synthesized netlist (skips SYNTHESIS)
        - input_filelist takes priority over origin_verilog for synthesis when both exist
        - All input files are copied to workspace/origin/ directory
    """
    # create workspace directory
    import os
    os.makedirs(directory, exist_ok=True)
    
    # create workspace instance
    workspace = Workspace()
    
    #update config
    workspace.design.name = parameters.data["Design"]
    workspace.design.top_module = parameters.data["Top module"]         
    workspace.pdk = pdk
    workspace.parameters = parameters
    
    # update path
    workspace.directory = directory
    workspace.parameters.path = f"{directory}/parameters.json"
    workspace.flow.path = f"{directory}/flow.json"
    
    # update orign files to workspace origin folder
    import shutil
    os.makedirs(f"{directory}/origin", exist_ok=True)
    if os.path.exists(origin_def):
        shutil.copy(origin_def, f"{directory}/origin/{os.path.basename(origin_def)}")
        workspace.design.origin_def = f"{directory}/origin/{os.path.basename(origin_def)}"

    if os.path.exists(origin_verilog):
        shutil.copy(origin_verilog, f"{directory}/origin/{os.path.basename(origin_verilog)}")
        workspace.design.origin_verilog = f"{directory}/origin/{os.path.basename(origin_verilog)}"

    if os.path.exists(input_filelist):
        shutil.copy(input_filelist, f"{directory}/origin/{os.path.basename(input_filelist)}")
        workspace.design.input_filelist = f"{directory}/origin/{os.path.basename(input_filelist)}"
        
    if os.path.exists(pdk.sdc):
        shutil.copy(pdk.sdc, f"{directory}/origin/{os.path.basename(pdk.sdc)}")
        workspace.pdk.sdc = f"{directory}/origin/{os.path.basename(pdk.sdc)}"
    else:
        # create default sdc file
        from .workspace import create_default_sdc
        workspace.pdk.sdc = f"{directory}/origin/{workspace.design.name}.sdc"
        create_default_sdc(workspace)
        
    if os.path.exists(pdk.spef):
        shutil.copy(pdk.spef, f"{directory}/origin/{os.path.basename(pdk.spef)}")
        workspace.pdk.spef = f"{directory}/origin/{os.path.basename(pdk.spef)}"
        
    # create logger
    os.makedirs(f"{directory}/log", exist_ok=True)
    workspace.logger = create_logger(name=workspace.design.name,
                                     log_dir=f"{directory}/log")
    
    # save parameter
    save_parameter(workspace.parameters)
     
    return workspace

def log_workspace(workspace : Workspace):
    def format_string(text : str, len=20) -> str:
        return text.ljust(len, " ")
        
    workspace.logger.info("######################################################################")
    workspace.logger.info("workspace      : %s", workspace.directory)
    workspace.logger.info("PDK            : %s", workspace.pdk.name)
    workspace.logger.info("design         : %s", workspace.design.name)
    workspace.logger.info("top module     : %s", workspace.design.top_module)
    workspace.logger.info("origin def     : %s", workspace.design.origin_def)
    workspace.logger.info("origin verilog : %s", workspace.design.origin_verilog)
    workspace.logger.info("input filelist : %s", workspace.design.input_filelist)
    workspace.logger.info("sdc            : %s", workspace.pdk.sdc)
    workspace.logger.info("spef           : %s", workspace.pdk.spef)
    workspace.logger.info("######################################################################")
    workspace.logger.info("")
    workspace.logger.info("######################################################################")
    workspace.logger.info("parameters     : %s", workspace.parameters.path)
    workspace.logger.info("\n%s", dict_to_str(workspace.parameters.data))
    workspace.logger.info("######################################################################")
    workspace.logger.info("")
    workspace.logger.info("######################################################################")
    workspace.logger.info("flow           : %s", workspace.flow.path)
    workspace.logger.info("%s | %s | %s | %s", 
                              format_string("name"),
                              format_string("tool"),
                              format_string("state"),
                              format_string("runtime"))
    for step in workspace.flow.data.get("steps", []):
        workspace.logger.info("%s | %s | %s | %s", 
                              format_string(step.get("name", "")),
                              format_string(step.get("tool", "")),
                              format_string(step.get("state", "")),
                              format_string(step.get("runtime", "")))
    workspace.logger.info("######################################################################")

def create_default_sdc(workspace : Workspace):
    """
    Create SDC file based on PDK and workspace parameters.
    """
    sdc_content = []
    sdc_content.append("# Auto-generated SDC file\n")
    sdc_content.append("\n")
    sdc_content.append("set clk_name {} \n".format(workspace.parameters.data.get("Clock", "")))
    sdc_content.append("set clk_port_name {}\n".format(workspace.parameters.data.get("Clock", "")))
    sdc_content.append("set clk_freq_mhz {}\n".format(workspace.parameters.data.get("Frequency max [MHz]", 100)))
    sdc_content.append("set clk_period [expr 1000.0 / $clk_freq_mhz]\n")
    sdc_content.append("set clk_io_pct 0.2\n")
    sdc_content.append("set clk_port [get_ports $clk_port_name]\n")
    sdc_content.append("create_clock -name $clk_name -period $clk_period $clk_port\n")
    
    with open(workspace.pdk.sdc, 'w') as file:
        file.writelines(sdc_content)