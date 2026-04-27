#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import os
from copy import deepcopy
from dataclasses import dataclass, field

# ================= 1. IHP SG13G2 (Explicit) =================
SG13G2_PARAMETERS_TEMPLATE = {
    "PDK": "sg13g2",
    "Design": "", "Top module": "",
    "Die": {"Size": [], "Area": 0},
    "Core": {
        "Size": [], "Area": 0, "Bounding box": "",
        "Utilitization": 0.65, "Margin": [17.5, 17.5], "Aspect ratio": 1
    },
    "Max fanout": 20,
    "Target density": 0.65,
    "Target overflow": 0.1,
    "Global right padding": 0,
    "Cell padding x": 0,
    "Routability opt flag": 1,
    "Clock": "clk",
    "Frequency max [MHz]": 100,
    "Bottom layer": "Metal2",        
    "Top layer": "Metal5",           
    "Floorplan": {
        "Tap distance": 0,           
        "Auto place pin": {"layer": "Metal3", "width": 300, "height": 600, "sides": []},
        "Tracks": [
            {"layer": "Metal1", "x start": 0, "x step": 420, "y start": 0, "y step": 420},
            {"layer": "Metal2", "x start": 0, "x step": 480, "y start": 0, "y step": 480},  
            {"layer": "Metal3", "x start": 0, "x step": 420, "y start": 0, "y step": 420},
            {"layer": "Metal4", "x start": 0, "x step": 480, "y start": 0, "y step": 480},
            {"layer": "Metal5", "x start": 0, "x step": 420, "y start": 0, "y step": 420},
        ]
    },
    "PDN": {
        "IO": [
            {"net name": "VDD", "direction": "INOUT", "is power": True},
            {"net name": "VSS", "direction": "INOUT", "is power": False}
        ],
        "Global connect": [
            {"net name": "VDD", "instance pin name": "VDD", "is power": True},
            {"net name": "VSS", "instance pin name": "VSS", "is power": False}
        ],
        "Grid": {"layer": "Metal1", "power net": "VDD", "power ground": "VSS", "width": 0.44, "offset": 0},
        "Stripe": [
            {"layer": "Metal4", "power net": "VDD", "ground net": "VSS", "width": 1.6, "pitch": 20, "offset": 1},
            {"layer": "Metal5", "power net": "VDD", "ground net": "VSS", "width": 1.6, "pitch": 20, "offset": 1}
        ],
        "Connect layers": [{"layers": ["Metal1", "Metal5"]}, {"layers": ["Metal4", "Metal5"]}]
    }
}

# ================= 2. GF180MCU (Explicit) =================
GF180_PARAMETERS_TEMPLATE = {
    "PDK": "gf180mcu",
    "Design": "", "Top module": "",
    "Die": {"Size": [], "Area": 0},
    "Core": {
        "Size": [], "Area": 0, "Bounding box": "",
        "Utilitization": 0.50, "Margin": [20, 20], "Aspect ratio": 1
    },
    "Max fanout": 20,
    "Target density": 0.45,
    "Target overflow": 0.1,
    "Global right padding": 0,
    "Cell padding x": 0,
    "Routability opt flag": 1,
    "Clock": "clk",
    "Frequency max [MHz]": 100,
    "Bottom layer": "Metal1",        
    "Top layer": "Metal5",           
    "Floorplan": {
        "Tap distance": 0,           
        "Auto place pin": {"layer": "Metal3", "width": 400, "height": 800, "sides": []},
        "Tracks": [
            {"layer": "Metal1", "x start": 0, "x step": 480, "y start": 0, "y step": 480},
            {"layer": "Metal2", "x start": 0, "x step": 560, "y start": 0, "y step": 560},  
            {"layer": "Metal3", "x start": 0, "x step": 480, "y start": 0, "y step": 480},
            {"layer": "Metal4", "x start": 0, "x step": 560, "y start": 0, "y step": 560},
            {"layer": "Metal5", "x start": 0, "x step": 480, "y start": 0, "y step": 480},
        ]
    },
    "PDN": {
        "IO": [
            {"net name": "VDD", "direction": "INOUT", "is power": True},
            {"net name": "VSS", "direction": "INOUT", "is power": False}
        ],
        "Global connect": [
            {"net name": "VDD", "instance pin name": "VDD", "is power": True},
            {"net name": "VSS", "instance pin name": "VSS", "is power": False}
        ],
        "Grid": {"layer": "Metal1", "power net": "VDD", "power ground": "VSS", "width": 0.6, "offset": 0},
        "Stripe": [
            {"layer": "Metal4", "power net": "VDD", "ground net": "VSS", "width": 2.0, "pitch": 25, "offset": 1},
            {"layer": "Metal5", "power net": "VDD", "ground net": "VSS", "width": 2.0, "pitch": 25, "offset": 1}
        ],
        "Connect layers": [{"layers": ["Metal1", "Metal5"]}, {"layers": ["Metal4", "Metal5"]}]
    }
}
# ================= 3. SKY130 (Explicit) =================
SKY130_PARAMETERS_TEMPLATE = {
    "PDK": "sky130",
    "Design": "", "Top module": "",
    "Die": {"Size": [], "Area": 0},
    "Core": {
        "Size": [], "Area": 0, "Bounding box": "",
        "Utilitization": 0.40, "Margin": [10, 10], "Aspect ratio": 1
    },
    "Max fanout": 20,
    "Target density": 0.40,
    "Target overflow": 0.1,
    "Global right padding": 0,
    "Cell padding x": 0,
    "Routability opt flag": 1,
    "Clock": "clk",
    "Frequency max [MHz]": 100,
    "Bottom layer": "met1",        
    "Top layer": "met5",           
    "Floorplan": {
        "Tap distance": 0,           
        "Auto place pin": {"layer": "met3", "width": 300, "height": 600, "sides": []},
        "Tracks": [
            {"layer": "met1", "x start": 0, "x step": 340, "y start": 0, "y step": 340},
            {"layer": "met2", "x start": 0, "x step": 460, "y start": 0, "y step": 460},  
            {"layer": "met3", "x start": 0, "x step": 340, "y start": 0, "y step": 340},
            {"layer": "met4", "x start": 0, "x step": 460, "y start": 0, "y step": 460},
            {"layer": "met5", "x start": 0, "x step": 340, "y start": 0, "y step": 340},
        ]
    },
    "PDN": {
        "IO": [
            {"net name": "VPWR", "direction": "INOUT", "is power": True},
            {"net name": "VGND", "direction": "INOUT", "is power": False}
        ],
        "Global connect": [
            {"net name": "VPWR", "instance pin name": "VPWR", "is power": True},
            {"net name": "VGND", "instance pin name": "VGND", "is power": False}
        ],
        "Grid": {"layer": "met1", "power net": "VPWR", "power ground": "VGND", "width": 0.48, "offset": 0},
        "Stripe": [
            {"layer": "met4", "power net": "VPWR", "ground net": "VGND", "width": 1.6, "pitch": 20, "offset": 1},
            {"layer": "met5", "power net": "VPWR", "ground net": "VGND", "width": 1.6, "pitch": 20, "offset": 1}
        ],
        "Connect layers": [{"layers": ["met1", "met5"]}, {"layers": ["met4", "met5"]}]
    }
}
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
    "Cell padding x": 600,
    "Routability opt flag": 1,
    "Clock" : "",
    "Frequency max [MHz]" : 100,
    "Bottom layer" : "MET2",
    "Top layer" : "MET5"
}

# ================= 1. IHP SG13G2 Design Parameters =================
SG13G2_DESIGN_PARAMETERS = {
    "gcd": {
        "Design": "gcd",
        "Top module": "gcd",
        "Clock": "clk",
        "Frequency max [MHz]": 100,
    },
    "aes_cipher_top": {
        "Design": "aes",
        "Top module": "aes_cipher_top",
        "Clock": "clk",
        "Frequency max [MHz]": 125,
    },
    "picorv32a": {
        "Design": "picorv32",
        "Top module": "picorv32a",
        "Clock": "clk",
        "Frequency max [MHz]": 50,
    }
}

# ================= 2. GF180MCU Design Parameters =================
GF180_DESIGN_PARAMETERS = {
    "gcd": {
        "Design": "gcd",
        "Top module": "gcd",
        "Clock": "clk",
        "Frequency max [MHz]": 50,
    },
    "aes_cipher_top": {
        "Design": "aes",
        "Top module": "aes_cipher_top",
        "Clock": "clk",
        "Frequency max [MHz]": 100,
    },
    "picorv32a": {
        "Design": "picorv32",
        "Top module": "picorv32a",
        "Clock": "clk",
        "Frequency max [MHz]": 33,
    }
}

# ================= 3. SKY130 Design Parameters =================
SKY130_DESIGN_PARAMETERS = {
    "gcd": {
        "Design": "gcd",
        "Top module": "gcd",
        "Clock": "clk",
        "Frequency max [MHz]": 100,
    },
    "aes_cipher_top": {
        "Design": "aes",
        "Top module": "aes_cipher_top",
        "Clock": "clk",
        "Frequency max [MHz]": 100,
    },
    "picorv32a": {
        "Design": "picorv32",
        "Top module": "picorv32a",
        "Clock": "clk",
        "Frequency max [MHz]": 50,
    }
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
    
    # Using the match statement as requested
    match pdk_name.lower():
        case "ics55":
            parameters.data = deepcopy(ICS55_PARAMETERS_TEMPLATE)
        case "sg13g2" | "ihp130":
            parameters.data = deepcopy(SG13G2_PARAMETERS_TEMPLATE)
        case "gf180mcu" | "gf180":
            parameters.data = deepcopy(GF180_PARAMETERS_TEMPLATE)
        case "sky130":
            parameters.data = deepcopy(SKY130_PARAMETERS_TEMPLATE)
            
    return parameters

def get_design_parameters(pdk_name : str, design : str = "", path : str = "") -> Parameters:
    """
    Return parameters resolved by PDK and optional design name.
    """
    parameters = get_parameters(pdk_name, path)
    if not design:
        return parameters

    pdk_low = pdk_name.lower()
    design_low = design.lower()
    design_info = None

    # Match the PDK to its specific design parameter dictionary
    match pdk_low:
        case "ics55":
            design_info = ICS55_DESIGN_PARAMETERS.get(design_low)
        case "sg13g2" | "ihp130":
            # Assuming you created SG13G2_DESIGN_PARAMETERS dictionary
            design_info = SG13G2_DESIGN_PARAMETERS.get(design_low)
        case "gf180mcu" | "gf180":
            # Assuming you created GF180_DESIGN_PARAMETERS dictionary
            design_info = GF180_DESIGN_PARAMETERS.get(design_low)
        case "sky130":
            # Assuming you created SKY130_DESIGN_PARAMETERS dictionary
            design_info = SKY130_DESIGN_PARAMETERS.get(design_low)

    # If design info was found for that specific PDK, update the parameters
    if design_info is not None:
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
