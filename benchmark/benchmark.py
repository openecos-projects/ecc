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

from chipcompiler.utility import json_read, csv_write

from .pdk import get_pdk
from .parameters import get_parameters

def has_value(value):
    return value is not None and value!=""

def run_benchmark(benchmark_json : str,
                  target_dir: str = "",
                  batch_name: str = "",
                  design:str = "",
                  max_processes = 10):
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
    
    # Run tasks with manual process management (max 10 concurrent processes)
    running_processes = []
    
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

def benchmark_result(benchmark_dir : str):
    statis_csv = f"{benchmark_dir}/benchmark.csv"
    
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
            peak_memory = 0
            is_success = True
            fp_inst_num = 0
            for step in flow_dict.get("steps", {}):
                state = step.get("state", "")
                step_name = step.get("name", "")
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
              header=header,
              data=results)
        
def benchmark_statis(benchmark_dir : str):
    statis_csv = f"{benchmark_dir}/benchmark.csv"
    
    header = [
        "Workspace",
        "Design",
        "peak memory (mb)",
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
            peak_memory = 0
            is_success = True
            fp_inst_num = 0
            for step in flow_dict.get("steps", {}):
                state = step.get("state", "")
                step_name = step.get("name", "")
                if "Success" == state:
                    match step_name:
                        case StepEnum.FLOORPLAN.value:
                            json_path = f"{workspace_dir}/{step_name}_iEDA/feature/{step_name}.db.json"
                            db_dict = json_read(file_path=json_path)
                            fp_inst_num = db_dict.get("Design Statis", {}).get("num_instances", 0)
                            step_result.append(fp_inst_num)
                        case StepEnum.NETLIST_OPT.value:
                            json_path = f"{workspace_dir}/{step_name}_iEDA/feature/{step_name}.db.json"
                            db_dict = json_read(file_path=json_path)
                            inst_num = db_dict.get("Design Statis", {}).get("num_instances", 0)
                            step_result.append(inst_num-fp_inst_num)
                        case StepEnum.PLACEMENT.value:
                            json_path = f"{workspace_dir}/{step_name}_iEDA/feature/{step_name}.step.json"
                            db_dict = json_read(file_path=json_path)
                            overflow = db_dict.get("place", {}).get("overflow", 0)
                            step_result.append(overflow)
                        case StepEnum.ROUTING.value:
                            json_path = f"{workspace_dir}/{step_name}_iEDA/feature/{step_name}.db.json"
                            db_dict = json_read(file_path=json_path)
                            wire_len = db_dict.get("Nets", {}).get("wire_len", 0)
                            step_result.append(wire_len)
                        case StepEnum.DRC.value:
                            json_path = f"{workspace_dir}/{step_name}_iEDA/feature/{step_name}.step.json"
                            db_dict = json_read(file_path=json_path)
                            drc_num = db_dict.get("drc", {}).get("number", 0)
                            step_result.append(drc_num)
                        case default:
                            step_result.append(state)
                                
                else:
                    step_result.append(state)
                    is_success = False
                # step_result.append(step.get("state", ""))
                memory = step.get("peak memory (mb)", 0)
                peak_memory = memory if memory>peak_memory else peak_memory
                
            
            success_num = success_num + 1 if is_success else success_num   
            # peak memory
            workspace_result.append(peak_memory)
            
            workspace_result.extend(step_result)
            total += 1
            
            results.append(workspace_result)
            
            print(f"process {dir} - {design_name} : {is_success}")
    
    csv_write(file_path=statis_csv,
              header=header,
              data=results)
            
    print(f"benchmark success {success_num} / {total}")