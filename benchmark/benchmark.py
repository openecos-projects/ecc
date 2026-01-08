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
    StateEnum
)

from chipcompiler.engine import (
    EngineDB,
    EngineFlow
)

from .pdk import get_pdk
from .parameters import get_parameters

def has_value(value):
    return value is not None and value!=""

def run_benchmark(benchmark_json : str,
                  target_dir: str = "",
                  batch_name: str = "",
                  design:str = ""):
    from chipcompiler.utility import json_read
    
    benchmarks = json_read(benchmark_json)
    
    value_is_ok = True
    
    value_is_ok = value_is_ok & has_value(benchmarks.get("target_dir", ""))
    value_is_ok = value_is_ok & has_value(benchmarks.get("batch_name", ""))
    value_is_ok = value_is_ok & has_value(benchmarks.get("pdk", ""))
    
    if not value_is_ok:
        raise ValueError("Invalid benchmark json file, missing target_dir or batch_name or pdk")
    
    target_dir = target_dir if target_dir != "" else benchmarks.get("target_dir", "")
    batch_name = batch_name if batch_name != "" else benchmarks.get("batch_name", "")
    task_dir = f"{target_dir}/{batch_name}"
    os.makedirs(task_dir, exist_ok=True)
    
    designs = benchmarks.get("designs", [])
    
    # Prepare tasks
    import multiprocessing
    
    # Create a list to hold all design tasks
    design_tasks = []
    for design_info in designs:
        if design != "" and design != design_info.get("Design", ""):
            continue
        
        value_is_ok = True
        value_is_ok = value_is_ok & has_value(design_info.get("id", ""))
        value_is_ok = value_is_ok & has_value(design_info.get("rtl", ""))
        value_is_ok = value_is_ok & has_value(design_info.get("netlist", ""))
        value_is_ok = value_is_ok & has_value(design_info.get("Design", ""))
        value_is_ok = value_is_ok & has_value(design_info.get("Top module", ""))
        value_is_ok = value_is_ok & has_value(design_info.get("Clock", ""))
        value_is_ok = value_is_ok & has_value(design_info.get("Frequency max [MHz]", ""))
        if not value_is_ok:
            raise ValueError(f"Invalid design info for {design_info.get('id', '')}, missing required fields")
        
        # Collect task parameters
        design_tasks.append((f"{task_dir}/{design_info.get('id', '')}", 
                           benchmarks.get("pdk", ""),
                           design_info,))
    
    # Run tasks with manual process management (max 10 concurrent processes)
    max_processes = 10
    running_processes = []
    
    for task_args in design_tasks:
        # If we've reached max processes, wait for any to complete
        if len(running_processes) >= max_processes:
            # Check for completed processes
            for i, p in enumerate(running_processes):
                if not p.is_alive():
                    del running_processes[i]
                    break
            else:
                # No completed processes, wait briefly
                import time
                time.sleep(0.1)
                continue
        
        # Create a new non-daemon process
        p = multiprocessing.Process(target=run_single_design, args=task_args)
        p.daemon = False  # Ensure process is not daemon so it can create children
        p.start()
        running_processes.append(p)
    
    # Wait for all remaining processes to complete
    for p in running_processes:
        p.join()
  
def run_single_design(workspace_dir : str,
                      pdk_name : str,
                      design_info : dict):
    os.makedirs(workspace_dir, exist_ok=True)
    
    parameters = get_parameters(pdk_name=pdk_name)
    
    parameters.data["Design"] = design_info.get("Design", "")
    parameters.data["Top module"] = design_info.get("Top module", "")
    parameters.data["Clock"] = design_info.get("Clock", "")
    parameters.data["Frequency max [MHz]"] = design_info.get("Frequency max [MHz]", 100)
    
    pdk = get_pdk(pdk_name=pdk_name)

    input_rtl = design_info.get("rtl", "")
    input_verilog = design_info.get("netlist", "")
    input_filelist = design_info.get("filelist", "")

    # Determine the input file for the first step:
    # - If RTL/filelist exists: use RTL as input, add SYNTHESIS step
    # NOTE: filelist has higher priority than RTL
    # - Otherwise: use pre-synthesized netlist, skip SYNTHESIS
    # NOTE: origin_verilog can be either RTL or netlist depending on the flow
    steps = []
    input_netlist = ""
    if os.path.exists(input_rtl) or os.path.exists(input_filelist):
        input_netlist = input_rtl
        # Filelist Already passed in create_workspace parameter
        steps.append((StepEnum.SYNTHESIS, "yosys", StateEnum.Unstart))
    elif os.path.exists(input_verilog):
        input_netlist = input_verilog
        input_filelist = ""
            
    steps.append((StepEnum.FLOORPLAN, "iEDA", StateEnum.Unstart))
    steps.append((StepEnum.NETLIST_OPT, "iEDA", StateEnum.Unstart))
    steps.append((StepEnum.PLACEMENT, "iEDA", StateEnum.Unstart))
    steps.append((StepEnum.CTS, "iEDA", StateEnum.Unstart))
    steps.append((StepEnum.LEGALIZATION, "iEDA", StateEnum.Unstart))
    steps.append((StepEnum.ROUTING, "iEDA", StateEnum.Unstart))
    steps.append((StepEnum.DRC, "iEDA", StateEnum.Unstart))
    steps.append((StepEnum.FILLER, "iEDA", StateEnum.Unstart))
            
    # create workspace
    workspace = create_workspace(
        directory=workspace_dir,
        origin_def="",
        origin_verilog=input_netlist,
        pdk=pdk,
        parameters=parameters,
        input_filelist=input_filelist
    )
    
    engine_flow = EngineFlow(workspace=workspace)
    if not engine_flow.has_init():
        for step, tool, state in steps:
            engine_flow.add_step(step=step, tool=tool, state=state)
    engine_flow.create_step_workspaces()
    
    log_workspace(workspace=workspace)
    
    engine_flow.run_steps()
    
if __name__ == "__main__":
    benchmark_json = f"{root}/test/ics55_benchmark.json"
    
    run_benchmark(benchmark_json=benchmark_json)

    exit(0)
