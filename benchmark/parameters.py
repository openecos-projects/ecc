import sys
import os

current_dir = os.path.split(os.path.abspath(__file__))[0]
root = current_dir.rsplit('/', 1)[0]
sys.path.append(root)

from chipcompiler.data import Parameters
from chipcompiler.data.parameter import get_parameters as _get_parameters

def benchmark_parameters(pdk_name : str, design : str = "", path : str = "") -> Parameters:
    """
    Return the Parameters instance based on the given pdk name.
    """
    parameters = _get_parameters(pdk_name, path)
    
    if pdk_name.lower() == "ics55":
        benchmark_json = os.path.join(current_dir, "ics55_benchmark.json")
        if not parameter_ics55(design, parameters, benchmark_json):
            return None
        
    return parameters

def parameter_ics55(design : str, parameters : Parameters, benchmark_json : str) -> bool:
    from chipcompiler.utility import json_read
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
            
            return True

    return False