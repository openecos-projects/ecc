#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from chipcompiler.workspaces import Parameters

def get_parameters(pdk_name : str) -> Parameters:
    """
    Return the Parameters instance based on the given pdk name.
    """
    if pdk_name.lower() == "sky130":
        return parameter_sky130()
    else:
        return Parameters()

def parameter_sky130() -> Parameters:
    parameters = Parameters()
    
    return parameters