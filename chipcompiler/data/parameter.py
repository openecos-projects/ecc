#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import os

from dataclasses import dataclass, field

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

def get_parameters(pdk_name : str, design : str = "", path : str = "", current_dir : str = "") -> Parameters:
    """
    Return the Parameters instance based on the given pdk name.
    """
    if current_dir != "" and not os.path.isdir(current_dir):
        current_dir = ""
    if path == "":
        if current_dir == "":
            return Parameters()
        path = f"{current_dir}/{pdk_name.lower()}_parameter.json"
    if pdk_name.lower() == "sky130":
        return parameter_sky130(design, path, current_dir)
    elif pdk_name.lower() == "ics55":
        return parameter_ics55(design, path, current_dir)
    else:
        return Parameters()

def parameter_ics55(design : str, path : str, current_dir : str) -> Parameters:
    parameters = Parameters()
    
    from chipcompiler.utility import json_read
    parameters.path = path
    parameters.data = json_read(path)
    
    if current_dir == "":
        raise FileNotFoundError("current_dir is empty; cannot locate ics55_benchmark.json")

    from chipcompiler.utility import json_read
    benchmark_json = f"{current_dir}/ics55_benchmark.json"
    if not os.path.isfile(benchmark_json):
        raise FileNotFoundError(f"ics55_benchmark.json not found: {benchmark_json}")
    benchmarks = json_read(benchmark_json)
    designs = benchmarks.get("designs", [])
    for design_info in designs:
        if design == design_info.get("Design", ""):
            parameters.data["Design"] = design_info.get("Design", "")
            parameters.data["Top module"] = design_info.get("Top module", "")
            parameters.data["Clock"] = design_info.get("Clock", "")
            parameters.data["Frequency max [MHz]"] = design_info.get("Frequency max [MHz]", 100)

    return parameters

def parameter_sky130(design : str, path : str, current_dir : str) -> Parameters:
    parameters = Parameters()
    
    from chipcompiler.utility import json_read
    parameters.path = path
    parameters.data = json_read(path)
    
    match design.lower():
        case "gcd":
            parameters.data["Design"] = "gcd"
            parameters.data["Top module"] = "gcd"
            parameters.data["Clock"] = "clk"
            parameters.data["Frequency max [MHz]"] = 100
        
    return parameters
