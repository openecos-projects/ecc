#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from enum import Enum
from dataclasses import dataclass, field

class StepEnum(Enum):
    """RTL2GDS flow step names"""
    RTL2GDS = "RTL2GDS"
    INIT = "Init"
    SOC = "SOC"
    FUNC_SIM = "Functional simulation"
    SYNTHESIS = "Synthesis"
    FLOORPLAN = "Floorplan"
    NETLIST_OPT = "fixFanout"
    PLACEMENT = "place"
    CTS = "CTS"
    PNP = "PNP"
    TIMING_OPT = "Timing optimization"
    TIMING_OPT_DRV = "optDrv"
    TIMING_OPT_HOLD = "optHold"
    TIMING_OPT_SETUP = "optSetup"
    LEGALIZATION = "legalization"
    ROUTING = "route"
    FILLER = "filler"
    GDS = "GDS"    
    SIGNOFF = "Signoff"
    STA = "sta"
    DRC = "drc"
    RCX = "RCX"
    ABSTRACT_LEF = "Abstract lef"
    MERGE = "GDS merge"
    HARDEN = "Harden"

class StateEnum(Enum):
    """flow running state"""
    Invalid = "Invalid" # ecc tools or config invalid
    Unstart = "Unstart" # step unstart
    Success = "Success" # step run success
    Ongoing = "Ongoing" # step is running
    Pending = "Pending" # step is pending
    Imcomplete = "Incomplete" # step is failed
    # Ignored = "Ignored" # step result do not affect flow step
    

###########################################################################
# step definition for chip design flow in json format
# step_definition =
# {
#     "name" : "", # step name
#     "tool" : "", # eda tool name
#     "state" : "", # step state
#     "runtime" : "", # step run time
#     "info" : {} # step additional infomation
# }
###########################################################################

@dataclass
class StepMetrics:
    """
    Dataclass for step metrics
    """
    path : str = "" # metrics file path
    data : dict = field(default_factory=dict) # metrics data
    report : list = field(default_factory=list) # metrics report

###########################################################################
# step metrics definition in json format
# step_metrics =
# {
#     "name" : "", # step name
#     "tool" : "", # eda tool name
# }
###########################################################################

def load_metrics(path : str) -> StepMetrics:
    from chipcompiler.utility import json_read
    metrics = StepMetrics() 
    metrics.path = path
    metrics.data = json_read(path)
    return metrics

def save_metrics(metrics : StepMetrics) -> bool:
    from chipcompiler.utility import json_write
    return json_write(file_path=metrics.path,
                      data=metrics.data)