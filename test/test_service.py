#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import sys
import os

current_dir = os.path.split(os.path.abspath(__file__))[0]
root = current_dir.rsplit('/', 1)[0]
sys.path.append(root)

from chipcompiler.data import (
    create_workspace,
    log_workspace,
    StepEnum,
    StateEnum,
    get_pdk
)

from chipcompiler.engine import (
    EngineDB,
    EngineFlow
)

from chipcompiler.services import (
    ECCService,
    ecc_service,
    ECCRequest,
    ECCResponse
)

from benchmark import get_parameters

def test_sky130_gcd():
    workspace_dir="{}/test/examples/sky130_gcd1".format(root)

    input_def = ""
    input_verilog = "{}/chipcompiler/thirdparty/iEDA/scripts/design/sky130_gcd/result/verilog/gcd.v".format(root)
    
    ecc_serv = ecc_service()
    
    parameters=get_parameters("sky130", "gcd")
    
    ecc_req = ECCRequest(
        cmd = "create_workspace",
        data = {
            "directory" : workspace_dir,
            "pdk" : "sky130",
            "parameters" : parameters.data,
            "origin_def" : input_def,
            "origin_verilog" : input_verilog,
            "rtl_list" : ""
        }
    )
    ecc_response = ecc_serv.create_workspace(ecc_req)
    
    ecc_req = ECCRequest(
        cmd = "load_workspace",
        data = {
            "directory" : workspace_dir
        }
    )
    ecc_response = ecc_serv.load_workspace(ecc_req)
  

    
if __name__ == "__main__":
    test_sky130_gcd()

    exit(0)
