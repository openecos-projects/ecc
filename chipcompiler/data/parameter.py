#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from dataclasses import dataclass, field

@dataclass
class Parameters:
    """
    Dataclass for design parameters
    """
    path : str = "" # parameters file path
    data : dict = field(default_factory=dict) # parameters data

def load_paramter(path : str) -> Parameters:
    from chipcompiler.utility import json_read
    parameter = Parameters()
    parameter.path = path
    parameter.data = json_read(path)
    return parameter
    
def save_parameter(parameter : Parameters) -> bool:
    from chipcompiler.utility import json_write
    return json_write(file_path=parameter.path,
                      data=parameter.data)