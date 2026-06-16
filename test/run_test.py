#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import sys
import os

current_dir = os.path.split(os.path.abspath(__file__))[0]
root = current_dir.rsplit('/', 1)[0]
sys.path.append(root)

from chipcompiler.data import (
    create_workspace,
    load_workspace,
    log_workspace,
    log_parameters,
    StepEnum,
    StateEnum,
    get_pdk,
    get_design_parameters
)

from chipcompiler.engine import (
    EngineDB,
    EngineFlow
)

def run_gcd():
    workspace_dir="{}/test/examples/ics55_gcd_tool".format(root)
    input_def = ""
    input_verilog = "{}/test/fixtures/gcd/gcd.v".format(root) # RTL file
    pdk = get_pdk(pdk_name= "ics55",
                  pdk_root= "/nfs/share/home/zengzhisheng/debug_workspace/foundry/cx55/icsprout55-pdk")
    parameters=get_design_parameters("ics55", "gcd")
    
    workspace = create_workspace(
        directory=workspace_dir,
        origin_def=input_def,
        origin_verilog=input_verilog,
        pdk=pdk,
        parameters=parameters
    )
    # workspace = load_workspace(workspace_dir)
    
    from chipcompiler.engine import EngineDB
    # build engine_db for workspace
    engine_db = EngineDB(workspace=workspace)
    # build engine flow for workspace
    engine_flow = EngineFlow(workspace=workspace, engine_db=engine_db)
    if not engine_flow.has_init():
        from chipcompiler.rtl2gds import build_rtl2gds_flow
        steps = build_rtl2gds_flow()
        for step, tool, state in steps:
            engine_flow.add_step(step=step, tool=tool, state=state)
            
    engine_flow.create_step_workspaces()
    
    engine_flow.run_steps()

def run_os_xs():
    workspace_dir="{}/test/examples/ics55_os_xs".format(root)
    input_def = ""
    input_verilog = ""
    pdk = get_pdk(pdk_name= "ics55",
                  pdk_root= "/nfs/share/home/zengzhisheng/debug_workspace/foundry/cx55/icsprout55-pdk")
    parameters=get_design_parameters("ics55", "os_xs")
    input_filelist= "/nfs/share/home/qiming/dataSet/edaTest/xiangshanICS55Splited/rtl/filelist.f"

    workspace = create_workspace(
        directory=workspace_dir,
        origin_def=input_def,
        origin_verilog=input_verilog,
        pdk=pdk,
        parameters=parameters,
        input_filelist=input_filelist
    )
    # workspace = load_workspace(workspace_dir)
    
    from chipcompiler.engine import EngineDB
    # build engine_db for workspace
    engine_db = EngineDB(workspace=workspace)
    # build engine flow for workspace
    engine_flow = EngineFlow(workspace=workspace, engine_db=engine_db)
    if not engine_flow.has_init():
        from chipcompiler.rtl2gds import build_rtl2gds_flow
        steps = build_rtl2gds_flow()
        for step, tool, state in steps:
            engine_flow.add_step(step=step, tool=tool, state=state)
            
    engine_flow.create_step_workspaces()
    
    engine_flow.run_steps()

if __name__ == "__main__":    
    run_gcd()
    # run_os_xs()
    exit(0)
