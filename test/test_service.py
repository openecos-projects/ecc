#!/usr/bin/env python

import os
import sys

current_dir = os.path.split(os.path.abspath(__file__))[0]
root = current_dir.rsplit("/", 1)[0]
sys.path.append(root)


from benchmark import get_parameters  # noqa: E402
from chipcompiler.services import ECCRequest, ecc_service  # noqa: E402


def test_sky130_gcd():
    workspace_dir = f"{root}/test/examples/sky130_gcd"

    input_def = ""
    input_verilog = ""
    input_filelist = f"{root}/test/fixtures/gcd/filelist.f"
    ecc_serv = ecc_service()

    parameters = get_parameters("sky130", "gcd")

    # create workspace
    #####################################################
    ecc_req = ECCRequest(
        cmd="create_workspace",
        data={
            "directory": workspace_dir,
            "pdk": "sky130",
            "parameters": parameters.data,
            "origin_def": input_def,
            "origin_verilog": input_verilog,
            "filelist": input_filelist,
        },
    )
    ecc_response = ecc_serv.create_workspace(ecc_req)

    # load workspace
    #####################################################
    ecc_req = ECCRequest(cmd="load_workspace", data={"directory": workspace_dir})
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
    # ecc_req = ECCRequest(
    #     cmd = "rtl2gds",
    #     data = {
    #         "rerun" : True
    #     }
    # )
    # ecc_response = ecc_serv.rtl2gds(ecc_req)

    # test run single step
    #####################################################
    from chipcompiler.rtl2gds import build_rtl2gds_flow

    steps = build_rtl2gds_flow()
    for step, _tool, _state in steps:
        ecc_req = ECCRequest(cmd="run_step", data={"step": step.value, "rerun": False})
        # ecc_response = ecc_serv.run_step(ecc_req)
        # print(ecc_response)

    # test get step infomation
    #####################################################
    from chipcompiler.services import InfoEnum

    for step, _tool, _state in steps:
        for info_enum in InfoEnum:
            ecc_req = ECCRequest(cmd="get_info", data={"step": step.value, "id": info_enum.value})
            ecc_response = ecc_serv.get_info(ecc_req)
            print(ecc_response)

    print(1)


if __name__ == "__main__":
    test_sky130_gcd()

    exit(0)
