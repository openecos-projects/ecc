#!/usr/bin/env python

import os
from dataclasses import dataclass, field


@dataclass
class Parameters:
    """
    Dataclass for design parameters
    """

    path: str = ""  # parameters file path
    data: dict = field(default_factory=dict)  # parameters data


def load_parameter(path: str) -> Parameters:
    from chipcompiler.utility import json_read

    parameter = Parameters()
    parameter.path = path
    parameter.data = json_read(path)
    return parameter


def save_parameter(parameter: Parameters) -> bool:
    from chipcompiler.utility import json_write

    return json_write(file_path=parameter.path, data=parameter.data)


def get_parameters(
    pdk_name: str, design: str = "", path: str = "", current_dir: str = ""
) -> Parameters:
    """
    Return the Parameters instance based on the given pdk name.
    """
    # Check path
    if path == "":
        if current_dir == "":
            raise FileNotFoundError("current_dir or path must be provided to locate parameters")
        if not os.path.isdir(current_dir):
            raise FileNotFoundError(f"current_dir does not exist: {current_dir}")
        path = f"{current_dir}/{pdk_name.lower()}_parameter.json"

    if pdk_name.lower() == "sky130":
        return parameter_sky130(design, path)
    elif pdk_name.lower() == "ics55":
        benchmark_json = os.path.join(current_dir, "ics55_benchmark.json")
        return parameter_ics55(design, path, benchmark_json)
    else:
        return Parameters()


def parameter_ics55(design: str, path: str, benchmark_json: str) -> Parameters:
    parameters = Parameters()

    from chipcompiler.utility import json_read

    parameters.path = path
    parameters.data = json_read(path)

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

    return parameters


def parameter_sky130(design: str, path: str) -> Parameters:
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
