#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import sys
import os

current_dir = os.path.split(os.path.abspath(__file__))[0]
root = current_dir.rsplit('/', 1)[0]
sys.path.append(root)

from chipcompiler.data import (
    create_workspace,
    StepEnum,
    StateEnum
)

from chipcompiler.engine import (
    EngineDB,
    EngineFlow
)

from pdk import get_pdk
from parameters import get_parameters

def test_ics55_gcd():
    gcd_dir="{}/test/examples/ics55_test".format(root)

    input_def = ""
    input_verilog = "/nfs/home/huangzengrong/ecos/testcase/gcd/gcd.v"

    parameters=get_parameters("ics55", "gcd")
    pdk = get_pdk("ics55")

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
    engine_flow.run_steps()

if __name__ == "__main__":
    test_ics55_gcd()