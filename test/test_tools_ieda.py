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

def test_sky130_gcd():
    workspace_dir="{}/test/examples/sky130_gcd2".format(root)
    
    input_def = ""
    input_verilog = "{}/chipcompiler/thirdparty/iEDA/scripts/design/sky130_gcd/result/verilog/gcd.v".format(root) # verilog file

    # sdc="{}/chipcompiler/thirdparty/iEDA/scripts/foundry/sky130/sdc/gcd.sdc".format(root)
    spef="{}/chipcompiler/thirdparty/iEDA/scripts/foundry/sky130/spef/gcd.spef".format(root)
    
    parameters=get_parameters("sky130", "gcd")
    pdk = get_pdk("sky130")
    pdk.spef = spef

    workspace = create_workspace(
        directory=workspace_dir,
        origin_def=input_def,
        origin_verilog=input_verilog,
        pdk=pdk,
        parameters=parameters
    )
    
    # after create workspace, copy origin files to workspace origin folder
    # use the origin def and verilog in workspace for the first step.   
    # create eda tool instance
    engine_flow = EngineFlow(workspace=workspace)
    if not engine_flow.has_init():
        engine_flow.add_step(step=StepEnum.FLOORPLAN, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.NETLIST_OPT, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.PLACEMENT, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.CTS, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.TIMING_OPT_DRV, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.TIMING_OPT_HOLD, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.LEGALIZATION, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.ROUTING, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.DRC, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.FILLER, tool="iEDA", state=StateEnum.Unstart)
        
    engine_flow.create_step_workspaces()
    
    log_workspace(workspace=workspace)

    # engine_flow.init_db_engine()
    engine_flow.run_steps()
  

def test_ics55_gcd():
    workspace_dir="{}/test/examples/ics55_gcd".format(root)

    input_def = ""
    input_verilog = "/nfs/home/huangzengrong/ecos/testcase/gcd/gcd.v" # RTL file
    # sdc="/nfs/home/huangzengrong/ecos/testcase/gcd/default.sdc"
    # sdc="{}/chipcompiler/thirdparty/iEDA/scripts/foundry/sky130/sdc/gcd.sdc".format(root)
    spef="{}/chipcompiler/thirdparty/iEDA/scripts/foundry/sky130/spef/gcd.spef".format(root)

    parameters=get_parameters("ics55", "gcd")
    # use special different pdk setting for yosys
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
        engine_flow.add_step(step=StepEnum.FLOORPLAN, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.NETLIST_OPT, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.PLACEMENT, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.CTS, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.LEGALIZATION, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.ROUTING, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.DRC, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.FILLER, tool="iEDA", state=StateEnum.Unstart)
    engine_flow.create_step_workspaces()
    
    log_workspace(workspace=workspace)
    
    engine_flow.run_steps()
    
def test_ics55(design_name: str, target_dir: str = "", design_dir_alias=""):   
    workspace_dir = f"{target_dir}/{design_name}" if target_dir != "" else f"{root}/test/examples/{design_name}"

    # benchmark path
    benchmark_dir = "/nfs/share/home/qiming/benchmark/dataset/rtl/ics55"
    
    input_def = ""
    design_dir = design_dir_alias if design_dir_alias != "" else design_name
    input_verilog = f"{benchmark_dir}/{design_dir}/rtl/{design_name}.v" # verilog file

    spef=""

    parameters=get_parameters("ics55", design_name)
    # use special different pdk setting for yosys
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
        engine_flow.add_step(step=StepEnum.FLOORPLAN, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.NETLIST_OPT, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.PLACEMENT, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.CTS, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.LEGALIZATION, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.ROUTING, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.DRC, tool="iEDA", state=StateEnum.Unstart)
        engine_flow.add_step(step=StepEnum.FILLER, tool="iEDA", state=StateEnum.Unstart)
    engine_flow.create_step_workspaces()
    
    log_workspace(workspace=workspace)
    
    engine_flow.run_steps()
    
if __name__ == "__main__":
    test_sky130_gcd()
    
    # test_ics55_gcd()
    
    # test_ics55(design_name="ysyx_23060170", 
    #            target_dir="/nfs/home/huangzengrong/benchmark/test",
    #            design_dir_alias="stage_b_ysyx_23060170")

    exit(0)
