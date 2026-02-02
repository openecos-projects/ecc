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

from benchmark import get_parameters

def test_ics55_gcd():
    workspace_dir="{}/test/examples/ics55_gcd".format(root)

    input_def = ""
    input_verilog = "{}/test/fixtures/benchmark/dummy/gcd.v".format(root) # RTL file
    spef="{}/chipcompiler/thirdparty/ecc-tools/scripts/foundry/sky130/spef/gcd.spef".format(root)
    parameters=get_parameters("ics55", "gcd")
    pdk = get_pdk("ics55")
    pdk.spef = spef

    workspace = create_workspace(
        directory=workspace_dir,
        origin_def=input_def,
        origin_verilog=input_verilog,
        pdk=pdk,
        parameters=parameters
    )

    engine_flow = EngineFlow(workspace=workspace)
    if not engine_flow.has_init():
        engine_flow.add_step(step=StepEnum.SYNTHESIS, tool="yosys", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.FLOORPLAN, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.NETLIST_OPT, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.PLACEMENT, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.CTS, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.LEGALIZATION, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.ROUTING, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.DRC, tool="ecc", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.FILLER, tool="ecc", state=StateEnum.Unstart)
    engine_flow.create_step_workspaces()
    
    log_workspace(workspace=workspace)
    
    engine_flow.run_steps()
    
if __name__ == "__main__":
    test_ics55_gcd()

    exit(0)
