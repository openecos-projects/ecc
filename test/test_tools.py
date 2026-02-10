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

def test_ics55_gcd():
    workspace_dir="{}/test/examples/ics55_gcd_tool".format(root)

    input_def = ""
    input_verilog = "{}/test/fixtures/gcd/gcd.v".format(root) # RTL file
    parameters=get_design_parameters("ics55", "gcd")
    pdk = get_pdk("ics55")

    workspace = create_workspace(
        directory=workspace_dir,
        origin_def=input_def,
        origin_verilog=input_verilog,
        pdk=pdk,
        parameters=parameters
    )
    
    
    engine_flow = EngineFlow(workspace=workspace)
    if not engine_flow.has_init():
        from chipcompiler.rtl2gds import build_rtl2gds_flow
        steps = build_rtl2gds_flow()
        for step, tool, state in steps:
            engine_flow.add_step(step=step, tool=tool, state=state)
            
    engine_flow.create_step_workspaces()
    
    log_workspace(workspace=workspace)
    
    engine_flow.run_steps()
    
if __name__ == "__main__":    
    test_ics55_gcd()

    exit(0)
