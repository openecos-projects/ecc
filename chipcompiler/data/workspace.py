#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from dataclasses import dataclass, field
from .parameter import (
    Parameters,
    get_parameters, 
    save_parameter, 
    load_parameter,
    update_parameters
)

from .pdk import get_pdk, PDK
from chipcompiler.utility import Logger, create_logger, dict_to_str, find_files
from chipcompiler.utility.filelist import parse_filelist, resolve_path, parse_incdir_directives
    
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
    subflow : dict = field(default_factory=dict) # sub flow for this step
    checklist : dict = field(default_factory=dict) # checklist for this step

    # step result info
    result : dict = field(default_factory=dict) # result info about this step

def copy_filelist_with_sources(input_filelist: str, workspace_dir: str, logger=None) -> str:
    """
    Copy filelist and all referenced source files + include directories to workspace/origin/.

    Maintains the original directory structure of source files relative to the filelist location.
    Supports +incdir directives with smart deduplication.

    Args:
        input_filelist: Path to the filelist file
        workspace_dir: Target workspace directory
        logger: Optional logger instance for logging operations

    Returns:
        Path to the copied filelist in workspace/origin/

    Raises:
        FileNotFoundError: If filelist file doesn't exist
        IOError: If file copy operations fail

    Example:
        >>> new_filelist_path = copy_filelist_with_sources(
        ...     "/project/design.f",
        ...     "/workspace/gcd"
        ... )
        >>> print(new_filelist_path)
        '/workspace/gcd/origin/design.f'
    """
    import os
    import shutil

    origin_dir = os.path.join(workspace_dir, "origin")
    os.makedirs(origin_dir, exist_ok=True)

    filelist_dir = os.path.dirname(os.path.abspath(input_filelist))
    copied_files = set()
    stats = {'copied': 0, 'missing': 0, 'incdir_copied': 0, 'incdir_skipped': 0}

    # Copy files listed in filelist
    try:
        source_files = parse_filelist(input_filelist)
    except Exception as e:
        if logger:
            logger.error(f"Failed to parse filelist {input_filelist}: {e}")
        raise

    for src_path in source_files:
        abs_src = resolve_path(src_path, filelist_dir)

        if not os.path.exists(abs_src):
            if logger:
                logger.warning(f"File not found (skipping): {abs_src}")
            stats['missing'] += 1
            continue

        rel_path = os.path.basename(src_path) if os.path.isabs(src_path) else src_path

        if rel_path in copied_files:
            if logger:
                logger.debug(f"Skipping duplicate: {rel_path}")
            continue

        if _copy_file_safely(abs_src, os.path.join(origin_dir, rel_path), logger, src_path):
            copied_files.add(rel_path)
            stats['copied'] += 1

    # Copy +incdir directories
    try:
        incdir_paths = parse_incdir_directives(input_filelist)
    except Exception as e:
        if logger:
            logger.warning(f"Failed to parse +incdir directives: {e}")
        incdir_paths = []

    for incdir_path in incdir_paths:
        abs_incdir = resolve_path(incdir_path, filelist_dir)

        if not os.path.exists(abs_incdir):
            if logger:
                logger.warning(f"Include directory not found: {abs_incdir}")
            continue

        if not os.path.isdir(abs_incdir):
            if logger:
                logger.warning(f"Include path is not a directory: {abs_incdir}")
            continue

        for root, dirs, files in os.walk(abs_incdir):
            for filename in files:
                src_file = os.path.join(root, filename)
                rel_from_filelist = os.path.relpath(src_file, filelist_dir)

                if rel_from_filelist in copied_files:
                    stats['incdir_skipped'] += 1
                    if logger:
                        logger.debug(f"Skipping duplicate from +incdir: {rel_from_filelist}")
                    continue

                dst_file = os.path.join(origin_dir, rel_from_filelist)
                if _copy_file_safely(src_file, dst_file, logger, f"+incdir/{src_file}"):
                    copied_files.add(rel_from_filelist)
                    stats['incdir_copied'] += 1

    # Copy filelist file itself
    new_filelist = os.path.join(origin_dir, os.path.basename(input_filelist))
    try:
        shutil.copy2(input_filelist, new_filelist)
    except Exception as e:
        if logger:
            logger.error(f"Failed to copy filelist: {e}")
        raise

    if logger:
        logger.info(
            f"Copied filelist and sources: "
            f"{stats['copied']} files from filelist, "
            f"{stats['incdir_copied']} files from +incdir, "
            f"{stats['missing']} missing, "
            f"{stats['incdir_skipped']} duplicates skipped"
        )

    return new_filelist


def _copy_file_safely(src: str, dst: str, logger, context: str) -> bool:
    """Copy a file with error handling and logging."""
    import os
    import shutil

    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        if logger:
            logger.debug(f"Copied: {src} -> {dst}")
        return True
    except Exception as e:
        if logger:
            logger.error(f"Error copying {context}: {e}")
        return False

                     
def create_workspace(directory : str,
                     origin_def : str,
                     origin_verilog : str,
                     pdk : PDK | str,
                     parameters : Parameters | dict,
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
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as error:
        return None
    
    # create workspace instance
    workspace = Workspace()
    
    # pdk 
    if isinstance(pdk, PDK):
        workspace.pdk = pdk
        
    if isinstance(pdk, str):
        workspace.pdk = get_pdk(pdk)    
    
    #update config
    if isinstance(parameters, Parameters):
        workspace.design.name = parameters.data["Design"]
        workspace.design.top_module = parameters.data["Top module"]         
        workspace.parameters = parameters
    
    if isinstance(parameters, dict):
        # format parameters
        workspace.parameters = get_parameters(pdk)
        update_parameters(parameters_src=parameters,
                          parameters_target=workspace.parameters.data)
        
        workspace.design.name = workspace.parameters.data["Design"]
        workspace.design.top_module = workspace.parameters.data["Top module"]         
    
    # update path
    workspace.directory = directory
    workspace.parameters.path = f"{directory}/parameters.json"
    workspace.flow.path = f"{directory}/flow.json"
    
    # create logger first (needed for copy operations)
    os.makedirs(f"{directory}/log", exist_ok=True)
    workspace.logger = create_logger(name=workspace.parameters.data["Design"],
                                     log_dir=f"{directory}/log")

    # update orign files to workspace origin folder
    import shutil
    os.makedirs(f"{directory}/origin", exist_ok=True)
    if os.path.exists(origin_def):
        shutil.copy(origin_def, f"{directory}/origin/{os.path.basename(origin_def)}")
        workspace.design.origin_def = f"{directory}/origin/{os.path.basename(origin_def)}"
    else:
        workspace.design.origin_def = f"{directory}/origin/{workspace.design.name}.def"

    if os.path.exists(origin_verilog):
        shutil.copy(origin_verilog, f"{directory}/origin/{os.path.basename(origin_verilog)}")
        workspace.design.origin_verilog = f"{directory}/origin/{os.path.basename(origin_verilog)}"
    else:
        workspace.design.origin_verilog = f"{directory}/origin/{workspace.design.name}.v"

    # Copy filelist and all referenced source files
    if os.path.exists(input_filelist):
        try:
            # Use new copy_filelist_with_sources to copy filelist + all RTL files
            workspace.design.input_filelist = copy_filelist_with_sources(
                input_filelist=input_filelist,
                workspace_dir=directory,
                logger=workspace.logger
            )
        except Exception as e:
            workspace.logger.error(f"Failed to copy filelist sources: {e}")
            workspace.logger.warning("Falling back to copying only filelist file")
            # Fallback: copy only filelist file (backward compatibility)
            shutil.copy(input_filelist, f"{directory}/origin/{os.path.basename(input_filelist)}")
            workspace.design.input_filelist = f"{directory}/origin/{os.path.basename(input_filelist)}"

    if os.path.exists(workspace.pdk.sdc):
        shutil.copy(workspace.pdk.sdc, f"{directory}/origin/{os.path.basename(workspace.pdk.sdc)}")
        workspace.pdk.sdc = f"{directory}/origin/{os.path.basename(workspace.pdk.sdc)}"
    else:
        # create default sdc file
        from .workspace import create_default_sdc
        workspace.pdk.sdc = f"{directory}/origin/{workspace.design.name}.sdc"
        create_default_sdc(workspace)
        
    if os.path.exists(workspace.pdk.spef):
        shutil.copy(workspace.pdk.spef, f"{directory}/origin/{os.path.basename(workspace.pdk.spef)}")
        workspace.pdk.spef = f"{directory}/origin/{os.path.basename(workspace.pdk.spef)}"

    # save parameter
    save_parameter(workspace.parameters)
     
    return workspace

def load_workspace(directory : str) -> Workspace:
    import os
    if not os.path.exists(directory):
        return None
    
    # create workspace instance
    workspace = Workspace()
    workspace.directory = directory

    parameters = load_parameter(f"{directory}/parameters.json")
    workspace.parameters = parameters
    
    pdk = get_pdk(pdk_name=parameters.data.get("PDK", ""))
    sdc_path = find_files(f"{directory}/origin", ".sdc")
    if len(sdc_path) > 0:
        pdk.sdc = sdc_path[0]
    spef_path = find_files(f"{directory}/origin", ".spef")
    if len(spef_path) > 0:
        pdk.spef = spef_path[0]
        
    workspace.pdk = pdk
    
    #update config
    workspace.design.name = parameters.data.get("Design", "")
    workspace.design.top_module = parameters.data.get("Top module", "")  
    def_path = find_files(f"{directory}/origin", ".def")
    def_gz_path = find_files(f"{directory}/origin", ".def.gz")
    if len(def_path) > 0:
        workspace.design.origin_def = def_path[0]
    if len(def_gz_path) > 0:
        workspace.design.origin_def = def_gz_path[0]
        
    verilog_path = find_files(f"{directory}/origin", ".v")
    verilog_gz_path = find_files(f"{directory}/origin", ".v.gz")
    if len(verilog_path) > 0:
        workspace.design.origin_verilog = verilog_path[0]
    if len(verilog_gz_path) > 0:
        workspace.design.origin_verilog = verilog_gz_path[0]
    
    filelist_path = f"{directory}/origin/filelist"
    if os.path.exists(filelist_path):
        workspace.design.input_filelist = filelist_path
        
    # update path
    workspace.flow.path = f"{directory}/flow.json"
    
    # create logger first (needed for copy operations)
    workspace.logger = create_logger(name=parameters.data["Design"],
                                     log_dir=f"{directory}/log")

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