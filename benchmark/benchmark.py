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
    load_parameter,
    get_pdk
)

from chipcompiler.engine import (
    EngineDB,
    EngineFlow
)

from chipcompiler.tools import build_step_metrics

from chipcompiler.utility import json_read, csv_write

from .get_parameters import get_parameters

def has_value(value):
    return value is not None and value!=""

def get_tasks(benchmark_json : str,
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
    
    # Create a list to hold all design tasks
    design_tasks = []
    for design_info in designs:
        if design != "" and design != design_info.get("Design", ""):
            continue
        
        value_is_ok = True
        value_is_ok = value_is_ok & has_value(design_info.get("id", ""))
        # value_is_ok = value_is_ok & has_value(design_info.get("filelist", ""))
        # if not value_is_ok:
        #     value_is_ok = value_is_ok & has_value(design_info.get("netlist", ""))
        # Input source: one of rtl, filelist, netlist must be provided
        has_rtl = has_value(design_info.get("rtl", ""))
        has_filelist = has_value(design_info.get("filelist", ""))
        has_netlist = has_value(design_info.get("netlist", ""))
        value_is_ok = value_is_ok & (has_rtl or has_filelist or has_netlist)
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
    
    return design_tasks


def run_benchmark(benchmark_json : str,
                  target_dir: str = "",
                  batch_name: str = "",
                  design:str = "",
                  max_processes = 10): 
    design_tasks = get_tasks(benchmark_json, target_dir, batch_name, design)
         
    # Run tasks with manual process management (max 10 concurrent processes)
    running_processes = []
    import multiprocessing
    for task_args in design_tasks:
        if len(running_processes) >= max_processes:
            # Check for completed processes
            for i, p in enumerate(running_processes):
                if not p.is_alive():
                    del running_processes[i]
                    break
                else:
                    # No completed processes, wait briefly
                    import time
                    time.sleep(5)
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

    # Priority: filelist > rtl > netlist
    steps = []
    input_netlist = ""
    if input_filelist and os.path.exists(input_filelist):
        # Use filelist for synthesis (input_netlist optional)
        input_netlist = input_filelist
        steps.append((StepEnum.SYNTHESIS, "yosys", StateEnum.Unstart))
    elif input_rtl and os.path.exists(input_rtl):
        # Use RTL for synthesis
        input_netlist = input_rtl
        steps.append((StepEnum.SYNTHESIS, "yosys", StateEnum.Unstart))
    elif input_verilog and os.path.exists(input_verilog):
        # Use pre-synthesized netlist, skip synthesis
        input_netlist = input_verilog
        input_filelist = ""
    else:
        raise ValueError(f"No valid input file found for design {design_info.get('Design', '')}")
            
    steps.append((StepEnum.FLOORPLAN, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.NETLIST_OPT, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.PLACEMENT, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.CTS, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.LEGALIZATION, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.ROUTING, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.DRC, "ecc", StateEnum.Unstart))
    steps.append((StepEnum.FILLER, "ecc", StateEnum.Unstart))
            
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
    if engine_flow.is_flow_success():
        return 
    engine_flow.create_step_workspaces()
    
    log_workspace(workspace=workspace)
    
    engine_flow.run_steps()

def benchmark_statis(benchmark_dir : str):
    statis_csv = f"{benchmark_dir}/benchmark.statis.csv"
    
    header = [
        "Workspace",
        "Design",
        f"{StepEnum.SYNTHESIS.value}",
        f"{StepEnum.FLOORPLAN.value}",
        f"{StepEnum.NETLIST_OPT.value}",
        f"{StepEnum.PLACEMENT.value}",
        f"{StepEnum.CTS.value}",
        f"{StepEnum.LEGALIZATION.value}",
        f"{StepEnum.ROUTING.value}",
        f"{StepEnum.DRC.value}",
        f"{StepEnum.FILLER.value}",
    ]
    
    total = 0
    success_num = 0
    results = []

    for root, dirs, files in os.walk(benchmark_dir):
        if root != benchmark_dir:
            break
        
        for dir in dirs:
            workspace_result = []
            
            # workspace name
            workspace_result.append(dir)
            
            workspace_dir = os.path.join(root, dir)
            
            # design name
            parameter_json = f"{workspace_dir}/parameters.json"
            parameter_dict = json_read(file_path=parameter_json)
            design_name = parameter_dict.get("Design", "")
            workspace_result.append(design_name)
            
            flow_json = f"{workspace_dir}/flow.json"
            flow_dict = json_read(file_path=flow_json)
            
            step_result = []
            is_success = True
            for step in flow_dict.get("steps", {}):
                state = step.get("state", "")
                step_result.append(state)
                if "Success" != state:
                    is_success = False
            
            success_num = success_num + 1 if is_success else success_num   
            
            workspace_result.extend(step_result)
            total += 1
            
            results.append(workspace_result)
            
            print(f"process {dir} - {design_name} : {is_success}")
    
    results.append([f"success", f"{success_num} / {total}"])
    print(f"benchmark success {success_num} / {total}")
    
    csv_write(file_path=statis_csv,
              header=[header],
              data=results)
        
def benchmark_metrics(benchmark_json : str,
              target_dir: str = "",
              batch_name: str = ""):
    statis_csv = f"{target_dir}/{batch_name}/benchmark.metrics.csv"
    
    design_tasks = get_tasks(benchmark_json, target_dir, batch_name)

    header = []
    header1 = []
    header2 = []
    init_header = False
    results = []
    
    pdk = None

    for workspace_dir, pdk_name, design_info in design_tasks:        
        workspace_result = []
        
        # workspace name
        workspace_result.append(design_info.get("id", ""))
        workspace_result.append(design_info.get("Design", ""))
        
        if pdk is None:
            pdk = get_pdk(pdk_name=pdk_name)
            
        parameters = get_parameters(pdk_name=pdk_name)
    
        parameters.data["Design"] = design_info.get("Design", "")
        parameters.data["Top module"] = design_info.get("Top module", "")
        parameters.data["Clock"] = design_info.get("Clock", "")
        parameters.data["Frequency max [MHz]"] = design_info.get("Frequency max [MHz]", 100)
    
        input_rtl = design_info.get("rtl", "")
        input_verilog = design_info.get("netlist", "")
        input_filelist = design_info.get("filelist", "")
    
        input_netlist = ""
        if input_filelist and os.path.exists(input_filelist):
            # Use filelist for synthesis (input_netlist optional)
            input_netlist = input_filelist
        elif input_rtl and os.path.exists(input_rtl):
            # Use RTL for synthesis
            input_netlist = input_rtl
        elif input_verilog and os.path.exists(input_verilog):
            # Use pre-synthesized netlist, skip synthesis
            input_netlist = input_verilog
            input_filelist = ""
        else:
            continue
             
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
            break
        engine_flow.create_step_workspaces()
        if engine_flow.is_flow_success() and len(header1) == 0:
            init_header = True
            header1.append("")
            header2.append("workspace")
            header1.append("")
            header2.append("design")
            header1.append("")
            header2.append("peak memory (mb)")
        
        step_result = []
        peak_memory = 0

        for workspace_step in engine_flow.workspace_steps:
            step = engine_flow.get_step(name=workspace_step.name,
                                        tool=workspace_step.tool)
            if engine_flow.check_state(name=workspace_step.name,
                                       tool=workspace_step.tool,
                                       state=StateEnum.Success):
                metrics = build_step_metrics(workspace=workspace,
                                             step=workspace_step)
                if metrics is None:
                    step_result.append(step["state"])
                else:
                    index = 0
                    for key, value in metrics.data.items():
                        if init_header :
                            header1.append(step["name"] if index == 0 else "")
                            header2.append(key)
                        
                        index += 1   
                        
                        step_result.append(value)    
            # step_result.append(step.get("state", ""))
            memory = step.get("peak memory (mb)", 0)
            peak_memory = memory if memory>peak_memory else peak_memory
            
        # peak memory
        workspace_result.append(peak_memory)
        workspace_result.extend(step_result)
        init_header = False
        
        results.append(workspace_result)
    
    header = [header1, header2]
    csv_write(file_path=statis_csv,
              header=header,
              data=results)