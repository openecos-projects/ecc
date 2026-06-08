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
    
def test_ics55_soc():
    workspace_dir="{}/test/examples/soc".format(root)

    workspace = load_workspace(workspace_dir)
    
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
    
def test_ics55_core():
    workspace_dir="{}/test/examples/core".format(root)

    workspace = load_workspace(workspace_dir)
    
    from chipcompiler.engine import EngineDB
    # build engine_db for workspace
    engine_db = EngineDB(workspace=workspace)
    # build engine flow for workspace
    engine_flow = EngineFlow(workspace=workspace, engine_db=engine_db)
    if not engine_flow.has_init():
        from chipcompiler.rtl2gds import build_harden_flow
        steps = build_harden_flow()
        for step, tool, state in steps:
            engine_flow.add_step(step=step, tool=tool, state=state)
            
    engine_flow.create_step_workspaces()
    
    engine_flow.run_steps()


if __name__ == "__main__":    
    test_ics55_soc()
    
    test_ics55_core()

    exit(0)