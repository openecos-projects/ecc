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
                "Size": [],
                "Bounding box": []
            },
            "Core" : {
                "Size": [],
                "Bounding box": [],
                "Utilitization": 0.4,
                "Margin" : [0, 0],
                "Aspect ratio" : 1
            },
            "Max fanout" : 20,
            "Target density" : 0.3,
            "Target overflow" : 0.1,
            "Clock" : ["clk"],
            "Frequency max [MHz]" : 100,
            "Bottom layer" : "MET2",
            "Top layer" : "MET5",
            "Floorplan" : {
                "Tap distance" : 58,
                "Auto place pin" : {
                  "layer" : "MET3",
                  "width" : 300,
                  "height" : 600,
                  "sides" : []  
                },
                "Tracks" :[
                    {
                        "layer" : "MET1",
                        "x start" : 0,
                        "x step" : 200,
                        "y start" : 0,
                        "y step" : 200
                    },
                    {
                        "layer" : "MET2",
                        "x start" : 0,
                        "x step" : 200,
                        "y start" : 0,
                        "y step" : 200
                    },
                    {
                        "layer" : "MET3",
                        "x start" : 0,
                        "x step" : 200,
                        "y start" : 0,
                        "y step" : 200
                    },
                    {
                        "layer" : "MET4",
                        "x start" : 0,
                        "x step" : 200,
                        "y start" : 0,
                        "y step" : 200
                    },
                    {
                        "layer" : "MET5",
                        "x start" : 0,
                        "x step" : 200,
                        "y start" : 0,
                        "y step" : 200
                    },
                    {
                        "layer" : "T4M2",
                        "x start" : 0,
                        "x step" : 800,
                        "y start" : 0,
                        "y step" : 800
                    },
                    {
                        "layer" : "RDL",
                        "x start" : 0,
                        "x step" : 5000,
                        "y start" : 0,
                        "y step" : 5000
                    }
                ]
            },
            "PDN" : {
                "IO" : [
                    {
                        "net name" : "VDD",
                        "direction" : "INOUT",
                        "is power" : 1
                    },
                    {
                        "net name" : "VDDIO",
                        "direction" : "INOUT",
                        "is power" : 1
                    },
                    {
                        "net name" : "VSS",
                        "direction" : "INOUT",
                        "is power" : 0
                    },
                    {
                        "net name" : "VSSIO",
                        "direction" : "INOUT",
                        "is power" : 0
                    }
                ],
                "Global connect" : [
                    {
                        "net name" : "VDD",
                        "instance pin name" : "VDD",
                        "is power" : 1
                    },
                    {
                        "net name" : "VDD",
                        "instance pin name" : "VDD1",
                        "is power" : 1
                    },
                    {
                        "net name" : "VDD",
                        "instance pin name" : "VNW",
                        "is power" : 1
                    },
                    {
                        "net name" : "VDDIO",
                        "instance pin name" : "VDDIO",
                        "is power" : 1
                    },
                    {
                        "net name" : "VSS",
                        "instance pin name" : "VSS",
                        "is power" : 0
                    },
                    {
                        "net name" : "VSS",
                        "instance pin name" : "VSS1",
                        "is power" : 0
                    },
                    {
                        "net name" : "VSS",
                        "instance pin name" : "VPW",
                        "is power" : 0
                    },
                    {
                        "net name" : "VSSIO",
                        "instance pin name" : "VSSIO",
                        "is power" : 0
                    }
                ],
                "grid" : {
                    "layer" : "MET1",
                    "power net" : "VDD",
                    "power ground" : "VSS",
                    "width" : 0.16,
                    "offset" : 0
                },
                "Stripe" : [
                    {
                        "layer" : "MET4",
                        "power net" : "VDD",
                        "ground net" : "VSS",
                        "width" : 1,
                        "pitch" : 16,
                        "offset" : 0.5                        
                    },
                    {
                        "layer" : "MET5",
                        "power net" : "VDD",
                        "ground net" : "VSS",
                        "width" : 1,
                        "pitch" : 16,
                        "offset" : 0.5                        
                    }
                ],
                "Connect layers" : [
                    {
                        "layers" : [
                            "MET1",
                            "MET5"
                        ]
                    },
                    {
                        "layers" : [
                            "MET4",
                            "MET5"
                        ]
                    }
                ]
            } 
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
                "Size": [],
                "Bounding box": []
            },
            "Core" : {
                "Size": [],
                "Bounding box": [],
                "Utilitization": 0.4,
                "Margin" : [0, 0],
                "Aspect ratio" : 1
            },
            "Max fanout" : 20,
            "Target density" : 0.3,
            "Target overflow" : 0.1,
            "Clock" : ["clk"],
            "Frequency max [MHz]" : 100,
            "Bottom layer" : "met1",
            "Top layer" : "met4",
            "Floorplan" : {
                "Tap distance" : 14,
                "Auto place pin" : {
                  "layer" : "met5",
                  "width" : 2000,
                  "height" : 2000,
                  "sides" : []  
                },
                "Tracks" :[
                    {
                        "layer" : "li1",
                        "x start" : 240,
                        "x step" : 480,
                        "y start" : 185,
                        "y step" : 370
                    },
                    {
                        "layer" : "met1",
                        "x start" : 185,
                        "x step" : 370,
                        "y start" : 185,
                        "y step" : 370
                    },
                    {
                        "layer" : "met2",
                        "x start" : 240,
                        "x step" : 480,
                        "y start" : 240,
                        "y step" : 480
                    },
                    {
                        "layer" : "met3",
                        "x start" : 370,
                        "x step" : 740,
                        "y start" : 370,
                        "y step" : 740
                    },
                    {
                        "layer" : "met4",
                        "x start" : 480,
                        "x step" : 960,
                        "y start" : 480,
                        "y step" : 960
                    },
                    {
                        "layer" : "met5",
                        "x start" : 185,
                        "x step" : 3330,
                        "y start" : 185,
                        "y step" : 3330
                    }
                ]
            },
            "PDN" : {
                "IO" : [
                    {
                        "net name" : "VDD",
                        "direction" : "INOUT",
                        "type" : "POWER"
                    },
                    {
                        "net name" : "VSS",
                        "direction" : "INOUT",
                        "type" : "GROUND"
                    }
                ],
                "Global connect" : [
                    {
                        "net name" : "VDD",
                        "instance pin name" : "vdd",
                        "is power" : 1
                    },
                    {
                        "net name" : "VDD",
                        "instance pin name" : "VPB",
                        "is power" : 1
                    },
                    {
                        "net name" : "VDD",
                        "instance pin name" : "VPWR",
                        "is power" : 1
                    },
                    {
                        "net name" : "VSS",
                        "instance pin name" : "gnd",
                        "is power" : 0
                    },
                    {
                        "net name" : "VSS",
                        "instance pin name" : "VGND",
                        "is power" : 0
                    },
                    {
                        "net name" : "VSS",
                        "instance pin name" : "VNB",
                        "is power" : 0
                    }
                ],
                "Grid" : {
                    "layer" : "met1",
                    "power net" : "VDD",
                    "ground net" : "VSS",
                    "width" : 0.48,
                    "offset" : 0
                },
                "Stripe" : [
                    {
                        "layer" : "met4",
                        "power net" : "VDD",
                        "ground net" : "VSS",
                        "width" : 1.60,
                        "pitch" : 27.14,
                        "offset" : 13.57                        
                    },
                    {
                        "layer" : "met5",
                        "power net" : "VDD",
                        "ground net" : "VSS",
                        "width" : 1.60,
                        "pitch" : 27.20,
                        "offset" : 13.60                      
                    }
                ],
                "Connect layers" : [
                    {
                        "layers" : [
                            "met1",
                            "met4"
                        ]
                    },
                    {
                        "layers" : [
                            "met4",
                            "met5"
                        ]
                    }
                ]
            } 
        }
    
    return parameters