#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from chipcompiler.data import Parameters

def get_parameters(pdk_name : str, design : str, path : str = "") -> Parameters:
    """
    Return the Parameters instance based on the given pdk name.
    """
    if pdk_name.lower() == "sky130":
        return parameter_sky130(design, path)
    elif pdk_name.lower() == "ics55":
        return parameter_ics55(design, path)
    else:
        return Parameters()

def parameter_ics55(design : str, path : str) -> Parameters:
    parameters = Parameters()

    if design.lower() == "gcd":
        parameters.path = path
        parameters.data = {
            "Design":"gcd",
            "Top module":"gcd",
            "Die" : {
                "Size": [1000, 1000],
                "Bounding box": [0, 0, 1000, 1000],
                "Utilitization": 0.3
            },
            "Core" : {
                "Size": [800, 800],
                "Bounding box": [100, 100, 900, 900],
                "Utilitization": 0.4
            },
            "Max fanout" : 20,
            "Target density" : 0.3,
            "Target overflow" : 0.1,
            "Clock" : ["clk"],
            "Frequency max [MHz]" : 100,
            "Bottom layer" : "MET2",
            "Top layer" : "MET5",
            "Buffers" : [
                "BUFX1H7R",
                "BUFX2H7R",
                "BUFX4H7R",
                "BUFX8H7R"
            ],
            "Fillers" : [
                "FILLER1H7R",
                "FILLER2H7R",
                "FILLER4H7R",
                "FILLER8H7R",
                "FILLER16H7R",
                "FILLER32H7R",
                "FILLER64H7R"
            ],
            "Tie high cell" : "TIEHIH7R",
            "Tie high port" : "Z",
            "Tie low cell" : "TIELOH7R",
            "Tie low port" : "Z"
        }

    return parameters

def parameter_sky130(design : str, path : str) -> Parameters:
    parameters = Parameters()

    if design.lower() == "gcd":
        parameters.path = path
        parameters.data = {
            "Design":"gcd",
            "Top module":"gcd",
            "Die" : {
                "Size": [1000, 1000],
                "Bounding box": [0, 0, 1000, 1000],
                "Utilitization": 0.3
                
            },
            "Core" : {
                "Size": [800, 800],
                "Bounding box": [100, 100, 900, 900],
                "Utilitization": 0.4
            },
            "Max fanout" : 20,
            "Target density" : 0.3,
            "Target overflow" : 0.1,
            "Clock" : ["clk"],
            "Frequency max [MHz]" : 100,
            "Bottom layer" : "met1",
            "Top layer" : "met4",
            "Buffers" : [
                "sky130_fd_sc_hs__buf_1",
                "sky130_fd_sc_hs__buf_8"
            ],
            "Fillers" : [
                "sky130_fd_sc_hs__fill_8",
                "sky130_fd_sc_hs__fill_4",
                "sky130_fd_sc_hs__fill_2",
                "sky130_fd_sc_hs__fill_1"
            ]
        }
    
    return parameters