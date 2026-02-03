#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from pydantic import BaseModel
from enum import Enum
from typing import List

class CMDEnum(Enum):
    create_workspace = "create_workspace"
    load_workspace = "load_workspace"
    delete_workspace = "delete_workspace"
    rtl2gds = "rtl2gds"
    run_step = "run_step"
    get_info = "get_info"

class ResponseEnum(Enum):
    success = "success"
    failed = "failed"
    error = "error"
    warning = "warning"

DATA_TEMPLATE = {
    "create_workspace" : {
        "requeset" : {
            "directory" : "",
            "pdk" : "",
            "parameters" : {},
            "origin_def" : "",
            "origin_verilog" : "",
            "filelist" : "",
            "rtl_list" : ""
        },
        "response" : {
            "directory" : ""
        }
    },
    
    "load_workspace" : {
        "requeset" : {
            "directory" : ""
        },
        "response" : {
            "directory" : ""
        }
    },
    
    "delete_workspace" : {
        "requeset" : {
            "directory" : ""
        },
        "response" : {
            "directory" : ""
        }
    },
    
    "rtl2gds" : {
        "requeset" : {
            "rerun" : False
        },
        "response" : {
            "rerun" : False
        }
    },
    
    "run_step" : {
        "requeset" : {
            "step" : "",
            "rerun" : False
        },
        "response" : {
            "step" : "",
            "state" : "Unstart"
        }
    },
    
    "get_info" : {
        "requeset" : {
            "step" : "",
            "id" : ""
        },
        "response" : {
            "step" : "",
            "id" : "",
            "info" : {}
        }
    },
}

class ECCRequest(BaseModel):
    """
    """
    cmd : str
    data : dict
    
class ECCResponse(BaseModel):
    """
    """
    cmd : str
    response : str
    data : dict
    message : list
