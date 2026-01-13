#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import sys
import os

current_dir = os.path.split(os.path.abspath(__file__))[0]
root = current_dir.rsplit('/', 1)[0]
sys.path.append(root)

from chipcompiler.data import Parameters

def get_parameters(pdk_name : str, design : str = "", path : str = "") -> Parameters:
    """
    Return the Parameters instance based on the given pdk name.
    """
    path = path if path != "" else f"{current_dir}/{pdk_name.lower()}_parameter.json"
    if pdk_name.lower() == "sky130":
        return parameter_sky130(design, path)
    elif pdk_name.lower() == "ics55":
        return parameter_ics55(design, path)
    else:
        return Parameters()

def parameter_ics55(design : str, path : str) -> Parameters:
    parameters = Parameters()
    
    from chipcompiler.utility import json_read
    parameters.path = path
    parameters.data = json_read(path)
    
    from chipcompiler.utility import json_read
    benchmark_json = f"{current_dir}/ics55_benchmark.json"
    benchmarks = json_read(benchmark_json)
    designs = benchmarks.get("designs", [])
    for design_info in designs:
        if design == design_info.get("Design", ""):
            parameters.data["Design"] = design_info.get("Design", "")
            parameters.data["Top module"] = design_info.get("Top module", "")
            parameters.data["Clock"] = design_info.get("Clock", "")
            parameters.data["Frequency max [MHz]"] = design_info.get("Frequency max [MHz]", 100)

    return parameters

def parameter_sky130(design : str, path : str) -> Parameters:
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