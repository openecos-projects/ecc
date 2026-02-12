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
    get_pdk,
    get_design_parameters
)

from chipcompiler.engine import (
    EngineDB,
    EngineFlow
)

from chipcompiler.server import (
    ECCService,
    ecc_service,
    ECCRequest,
    ECCResponse
)

def test_ics55_gcd():
    workspace_dir="{}/test/examples/ics55_gcd_service".format(root)
    pdk_root = os.path.abspath("{}/chipcompiler/thirdparty/icsprout55-pdk".format(root))
    if not os.path.isdir(pdk_root):
        raise RuntimeError(f"ics55 pdk root not found: {pdk_root}")

    input_def = ""
    input_verilog = ""
    input_filelist = "{}/test/fixtures/gcd/filelist.f".format(root)
    ecc_serv = ecc_service()
    
    parameters=get_design_parameters("ics55", "gcd")

    # set pdk root
    #####################################################
    ecc_req = ECCRequest(
        cmd = "set_pdk_root",
        data = {
            "pdk" : "ics55",
            "pdk_root" : pdk_root
        }
    )
    ecc_response = ecc_serv.set_pdk_root(ecc_req)
    print(ecc_response)
    if ecc_response.response != "success":
        raise RuntimeError(f"set_pdk_root failed: {ecc_response.message}")
    
    # create workspace
    #####################################################
    ecc_req = ECCRequest(
        cmd = "create_workspace",
        data = {
            "directory" : workspace_dir,
            "pdk" : "ics55",
            "pdk_root" : pdk_root,
            "parameters" : parameters.data,
            "origin_def" : input_def,
            "origin_verilog" : input_verilog,
            "filelist" : input_filelist
        }
    )
    ecc_response = ecc_serv.create_workspace(ecc_req)
    
    # load workspace
    #####################################################
    ecc_req = ECCRequest(
        cmd = "load_workspace",
        data = {
            "directory" : workspace_dir
        }
    )
    ecc_response = ecc_serv.load_workspace(ecc_req)
    print(ecc_response)
    
    # delete workspace
    #####################################################
    # ecc_req = ECCRequest(
    #     cmd = "delete_workspace",
    #     data = {
    #         "directory" : workspace_dir
    #     }
    # )
    # ecc_response = ecc_serv.delete_workspace(ecc_req)
    
    # run rtl2gds
    #####################################################
    ecc_req = ECCRequest(
        cmd = "rtl2gds",
        data = {
            "rerun" : True
        }
    )
    ecc_response = ecc_serv.rtl2gds(ecc_req)
    
    
    # test run single step
    #####################################################    
    # from chipcompiler.rtl2gds import build_rtl2gds_flow
    # steps = build_rtl2gds_flow()
    # for step, tool, state in steps:
    #     ecc_req = ECCRequest(
    #         cmd = "run_step",
    #         data = {
    #             "step" : step.value,
    #             "rerun" : False
    #         }
    #     )
    #     ecc_response = ecc_serv.run_step(ecc_req)
    #     print(ecc_response)
        
    # test get step infomation
    #####################################################
    # from chipcompiler.server import InfoEnum
    # for step, tool, state in steps:
    #     for info_enum in InfoEnum:           
    #         ecc_req = ECCRequest(
    #             cmd = "get_info",
    #             data = {
    #                 "step" : step.value,
    #                 "id" : info_enum.value
    #             }
    #         )
    #         ecc_response = ecc_serv.get_info(ecc_req)
    #         print(ecc_response)


if __name__ == "__main__":
    test_ics55_gcd()

    exit(0)
