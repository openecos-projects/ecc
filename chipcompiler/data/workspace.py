#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from dataclasses import dataclass, field
    
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

@dataclass
class Parameters:
    """
    Dataclass for design parameters
    """
    path : str = "" # parameters file path
    data : dict = field(default_factory=dict) # parameters data
    
@dataclass
class OriginDesign:
    """
    Dataclass for original design information
    """
    name : str = "" # design name
    top_module : str = "" # top module name
    origin_def : str = "" # original def file path
    origin_verilog : str = "" # original verilog file path
    
@dataclass
class Workspace:
    """
    Dataclass for workspace information
    """
    directory : str = "" # workspace directory
    design : OriginDesign = field(default_factory=OriginDesign) # original design info
    pdk : PDK = field(default_factory=PDK) # pdk information
    parameters : Parameters = field(default_factory=Parameters) # design parameters
    
@dataclass
class WorkspaceStep:
    """
    Dataclass for workspace step information, describe all the info for this task step.
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