#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import sys
import os

current_dir = os.path.split(os.path.abspath(__file__))[0]
root = current_dir.rsplit('/', 1)[0]
sys.path.append(root)
    
from chipcompiler.workspaces import Workspace
from chipcompiler.tools import create_step, create_workspace

from pdk import get_pdk
from parameters import get_parameters

def test_sky130_gcd():
    gcd_dir="{}/test/examples/sky130_test".format(root)
    
    input_def = ""
    input_verilog = "{}/chipcompiler/thirdparty/iEDA/scripts/design/sky130_gcd/result/verilog/gcd.v".format(root)

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
      
    # create eda tool instance
    eda_step = create_step(workspace=workspace,
                          step="floorplan",
                          eda="iEDA",
                          input_def="",
                          input_verilog=input_verilog)
    
    eda_step = create_step(workspace=workspace,
                          step="place",
                          eda="iEDA",
                          input_def=eda_step.output["def"],
                          input_verilog=eda_step.output["verilog"])
    
    eda_step = create_step(workspace=workspace,
                          step="cts",
                          eda="iEDA",
                          input_def=eda_step.output["def"],
                          input_verilog=eda_step.output["verilog"])
    
    eda_step = create_step(workspace=workspace,
                          step="timingopt",
                          eda="iEDA",
                          input_def=eda_step.output["def"],
                          input_verilog=eda_step.output["verilog"])

if __name__ == "__main__":
    test_sky130_gcd()

    exit(0)
