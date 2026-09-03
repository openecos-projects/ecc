#!/usr/bin/env python

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

ICS55_PARAMETERS_TEMPLATE = {
    "pdk": "ics55",
    "design": "",
    "top_module": "",
    "die": {"size": [], "area": 0},
    "core": {
        "size": [],
        "area": 0,
        "bounding_box": "",
        "utilitization": 0.4,
        "margin": [2, 2],
        "aspect_ratio": 1,
    },
    "max_fanout": 20,
    "target_density": 0.2,
    "target_overflow": 0.1,
    "global_right_padding": 0,
    "cell_padding_x": 300,
    "routability_opt_flag": 1,
    "clock": "",
    "frequency_max": 100,
    "bottom_layer": "MET2",
    "top_layer": "MET5",
    "sta_max_paths": 1000,
}
SG13G2_PARAMETERS_TEMPLATE = {
    "pdk": "sg13g2",
    "design": "",
    "top_module": "",
    "die": {"size": [], "area": 0},
    "core": {
        "size": [],
        "area": 0,
        "bounding_box": "",
        "utilitization": 0.65,
        "margin": [17.5, 17.5],
        "aspect_ratio": 1,
    },
    "max_fanout": 20,
    "target_density": 0.65,
    "target_overflow": 0.1,
    "global_right_padding": 0,
    "cell_padding_x": 0,
    "routability_opt_flag": 1,
    "clock": "",
    "frequency_max": 100,
    "bottom_layer": "Metal2",
    "top_layer": "Metal5",
    "sta_max_paths": 1000,
    "floorplan": {
        "tap_distance": 0,
        "auto_place_pin": {"layer": "Metal3", "width": 300, "height": 600, "sides": []},
        "tracks": [
            {"layer": "Metal1", "x_start": 0, "x_step": 420, "y_start": 0, "y_step": 420},
            {"layer": "Metal2", "x_start": 0, "x_step": 480, "y_start": 0, "y_step": 480},
            {"layer": "Metal3", "x_start": 0, "x_step": 420, "y_start": 0, "y_step": 420},
            {"layer": "Metal4", "x_start": 0, "x_step": 480, "y_start": 0, "y_step": 480},
            {"layer": "Metal5", "x_start": 0, "x_step": 420, "y_start": 0, "y_step": 420},
        ],
    },
    "pdn": {
        "io": [
            {"net_name": "VDD", "direction": "INOUT", "is_power": True},
            {"net_name": "VSS", "direction": "INOUT", "is_power": False},
        ],
        "global_connect": [
            {"net_name": "VDD", "instance_pin_name": "VDD", "is_power": True},
            {"net_name": "VSS", "instance_pin_name": "VSS", "is_power": False},
        ],
        "grid": {
            "layer": "Metal1",
            "power_net": "VDD",
            "power_ground": "VSS",
            "width": 0.44,
            "offset": 0,
        },
        "stripe": [
            {
                "layer": "Metal4",
                "power_net": "VDD",
                "ground_net": "VSS",
                "width": 1.6,
                "pitch": 20,
                "offset": 1,
            },
            {
                "layer": "Metal5",
                "power_net": "VDD",
                "ground_net": "VSS",
                "width": 1.6,
                "pitch": 20,
                "offset": 1,
            },
        ],
        "connect_layers": [{"layers": ["Metal1", "Metal5"]}, {"layers": ["Metal4", "Metal5"]}],
    },
}

ICS55_DESIGN_PARAMETERS = {
    "gcd": {
        "design": "gcd",
        "top_module": "gcd",
        "clock": "clk",
        "frequency_max": 100,
        "lec": {
            "use_undef": True,
        },
    }
}


@dataclass
class Parameters:
    """
    Dataclass for design parameters
    """

    path: Path | None = None  # workspace configuration file path
    data: dict = field(default_factory=dict)  # parameters data (flat snake_case keys)


def parameters_have_chip_identity(data: object) -> bool:
    from .workspace_config import parameters_have_chip_identity as _has_identity

    return _has_identity(data)


def _workspace_dir_for(path: Path) -> Path:
    """Return the workspace root for a config path under ``<workspace>/home``."""
    path = Path(path)
    if path.parent.name == "home":
        return path.parent.parent
    return path.parent


def load_parameter(path: Path) -> Parameters:
    from .workspace_config import (
        LEGACY_PARAMETERS_FILENAME,
        legacy_parameters_fallback,
        load_workspace_config,
    )

    parameter = Parameters()
    parameter.path = Path(path)
    workspace_dir = _workspace_dir_for(parameter.path)
    try:
        payload = load_workspace_config(workspace_dir)
    except FileNotFoundError:
        if parameter.path.name == LEGACY_PARAMETERS_FILENAME:
            # An explicit legacy parameters.json read on a workspace whose
            # TOML migration was deferred: load the JSON itself (normalized)
            # instead of silently returning nothing.
            parameter.data = legacy_parameters_fallback(workspace_dir)
        else:
            parameter.data = {}
        return parameter
    flow = payload.pop("_flow", {})
    parameter.data = payload
    if flow:
        parameter.data["_flow"] = flow
    return parameter


def reload_parameter(path: Path | None, current: Parameters | None = None) -> Parameters:
    """Reload the workspace configuration without dropping a valid identity."""
    loaded = Parameters() if path is None else load_parameter(path)
    if (
        current is not None
        and parameters_have_chip_identity(current.data)
        and not parameters_have_chip_identity(loaded.data)
    ):
        loaded.data = deepcopy(current.data)
        if loaded.path is None and current.path is not None:
            loaded.path = current.path
    return loaded


def save_parameter(parameter: Parameters) -> bool:
    from .workspace_config import save_workspace_config

    if parameter.path is None:
        return False
    data = dict(parameter.data)
    flow = data.pop("_flow", None)
    return save_workspace_config(_workspace_dir_for(parameter.path), data, flow)


def get_parameters(pdk_name: str = "", path: Path | None = None) -> Parameters:
    parameter_path = Path(path) if path else None
    if parameter_path is not None and parameter_path.is_file():
        return load_parameter(parameter_path)

    parameters = Parameters()
    parameters.path = parameter_path

    match pdk_name.lower():
        case "ics55":
            parameters.data = deepcopy(ICS55_PARAMETERS_TEMPLATE)
        case "sg13g2":
            parameters.data = deepcopy(SG13G2_PARAMETERS_TEMPLATE)

    return parameters


def get_design_parameters(pdk_name: str, design: str = "", path: Path | None = None) -> Parameters:
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


def update_parameters(parameters_src: dict, parameters_target: dict) -> dict:
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
