#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import os
from copy import deepcopy
from dataclasses import dataclass, field

ICS55_PARAMETERS_TEMPLATE = {
    "PDK":"ICS55",
    "Design":"",
    "Top module":"",
    "Die" : {
        "Size": [],
        "Area": 0
    },
    "Core" : {
        "Size": [],
        "Area" : 0,
        "Bounding box": "",
        "Utilitization": 0.4,
        "Margin" : [2, 2],
        "Aspect ratio" : 1
    },
    "Max fanout" : 20,
    "Target density" : 0.3,
    "Target overflow" : 0.1,
    "Global right padding": 0,
    "Clock" : "",
    "Frequency max [MHz]" : 100,
    "Bottom layer" : "MET2",
    "Top layer" : "MET5"
}

ICS55_DESIGN_PARAMETERS = {
    "gcd": {
        "Design": "gcd",
        "Top module": "gcd",
        "Clock": "clk",
        "Frequency max [MHz]": 100,
    }
}

@dataclass
class Parameters:
    """
    Dataclass for design parameters
    """
    path : str = "" # parameters file path
    data : dict = field(default_factory=dict) # parameters data

def load_parameter(path : str) -> Parameters:
    from chipcompiler.utility import json_read
    parameter = Parameters()
    parameter.path = path
    parameter.data = json_read(path)
    return parameter
    
def save_parameter(parameter : Parameters) -> bool:
    from chipcompiler.utility import json_write
    return json_write(file_path=parameter.path,
                      data=parameter.data)

def get_parameters(pdk_name : str = "", path : str = "") -> Parameters:
    """
    Return the Parameters instance based on the given pdk name.
    """
    if os.path.isfile(path):
        return load_parameter(path)
    
    parameters = Parameters()
    parameters.path = path
    
    match pdk_name.lower():
        case "ics55":
            parameters.data = deepcopy(ICS55_PARAMETERS_TEMPLATE)
            
    return parameters

def get_design_parameters(pdk_name : str, design : str = "", path : str = "") -> Parameters:
    """
    Return parameters resolved by PDK and optional design name.
    """
    parameters = get_parameters(pdk_name, path)
    if not design or pdk_name.lower() != "ics55":
        return parameters

    design_info = ICS55_DESIGN_PARAMETERS.get(design.lower())
    if design_info is None:
        return parameters

    parameters.data.update(design_info)
    return parameters

def update_parameters(parameters_src : dict, parameters_target : dict) -> dict:
    """
    Update parameters_target with data from parameters_src.
    If a value is a list, it will be replaced entirely.
    If a value is a dict, it will be updated recursively.
    Otherwise, the value will be replaced.
    """
    for key, value in parameters_src.items():
        if key in parameters_target:
            if isinstance(value, list):
                # If it's a list, replace entirely
                parameters_target[key] = value
            elif isinstance(value, dict) and isinstance(parameters_target[key], dict):
                # If it's a dict, update recursively
                update_parameters(value, parameters_target[key])
            else:
                # For other types, replace
                parameters_target[key] = value
        else:
            # If key doesn't exist, add it
            parameters_target[key] = value

    return parameters_target
