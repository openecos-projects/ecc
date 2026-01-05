#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import sys
import os

current_dir = os.path.split(os.path.abspath(__file__))[0]
root = current_dir.rsplit('/', 1)[0]
sys.path.append(root)

from chipcompiler.data import (
    create_workspace,
    log_workspace
)

from chipcompiler.engine import (
    EngineDB,
    EngineFlow
)

from pdk import get_pdk
from parameters import get_parameters

def test_sky130_gcd():
    gcd_dir="{}/test/examples/sky130_test".format(root)
    
    input_def = "/nfs/home/huangzengrong/ecos/aieda_fork/example/sky130_test/output/iEDA/result/gcd_floorplan.def.gz"
    input_verilog = "/nfs/home/huangzengrong/ecos/aieda_fork/example/sky130_test/output/iEDA/result/gcd_floorplan.v"
    # input_verilog = "{}/chipcompiler/thirdparty/iEDA/scripts/design/sky130_gcd/result/verilog/gcd.v".format(root)

    sdc="{}/chipcompiler/thirdparty/iEDA/scripts/foundry/sky130/sdc/gcd.sdc".format(root)
    spef="{}/chipcompiler/thirdparty/iEDA/scripts/foundry/sky130/spef/gcd.spef".format(root)
    
    parameters=get_parameters("sky130", "gcd")
    pdk = get_pdk("sky130")
    pdk.sdc = sdc
    pdk.spef = spef

    workspace = create_workspace(
        directory=gcd_dir,
        origin_def=input_def,
        origin_verilog=input_verilog,
        pdk=pdk,
        parameters=parameters
    )
    
    # after create workspace, copy origin files to workspace origin folder
    # use the origin def and verilog in workspace for the first step.   
    # create eda tool instance
    engine_flow = EngineFlow(workspace=workspace)
    engine_flow.build_default_steps()
    engine_flow.create_step_workspaces()
    
    log_workspace(workspace=workspace)

    # engine_flow.init_db_engine()
    engine_flow.run_steps()
  

def test_ics55_gcd():
    gcd_dir="{}/test/examples/ics55_test".format(root)

    input_def = ""
    input_verilog = "/nfs/home/huangzengrong/ecos/testcase/gcd/gcd.v"
    sdc="/nfs/home/huangzengrong/ecos/testcase/gcd/default.sdc"
    spef="{}/chipcompiler/thirdparty/iEDA/scripts/foundry/sky130/spef/gcd.spef".format(root)

    parameters=get_parameters("ics55", "gcd")
    # use special different pdk setting for yosys
    pdk = get_pdk("ics55")
    pdk.sdc = sdc
    pdk.spef = spef

    workspace = create_workspace(
        directory=gcd_dir,
        origin_def=input_def,
        origin_verilog=input_verilog,
        pdk=pdk,
        parameters=parameters
    )

    engine_flow = EngineFlow(workspace=workspace)
    engine_flow.build_default_steps()
    engine_flow.create_step_workspaces()
    
    log_workspace(workspace=workspace)
    
    engine_flow.run_steps()
    
if __name__ == "__main__":
    test_sky130_gcd()
    
    # test_ics55_gcd()

    exit(0)
