#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import time
from chipcompiler.data import Workspace, WorkspaceStep, StateEnum, StepEnum

from ..eda import SubFlowBase

class YosysSubFlow(SubFlowBase):
    def __init__(self, workspace : Workspace, workspace_step: WorkspaceStep):
        self.workspace = workspace
        self.workspace_step = workspace_step
        
        self.init_sub_flow()
        
        # set start time
        self.start_time = time.time()
        # set start memory
        self.start_memory = self.get_peak_memory()
    
    def init_sub_flow(self):
        from chipcompiler.utility import json_read
        data = json_read(self.workspace_step.subflow.get("path", ""))
        if len(data) > 0:
            self.workspace_step.subflow["steps"] = data.get("steps", [])
        else:
            self.build_sub_flow()

    def build_sub_flow(self) -> list:
        def subflow_template(step_name : str):
            return {
                "name" : step_name, # step name
                "state" : StateEnum.Unstart.value, # step state
                "runtime" : "", # step run time
                "peak memory (mb)" : 0, # step peak memory
                "info" : {} # step additional infomation
               }
            
        steps = []
        
        steps.append(subflow_template("run yosys"))
        steps.append(subflow_template("analysis"))
                
        self.workspace_step.subflow["steps"] = steps
        
        self.save()
    
    def save(self) -> bool:
        from chipcompiler.utility import json_write
        
        return json_write(file_path=self.workspace_step.subflow.get("path", ""), 
                          data=self.workspace_step.subflow)
    
    def get_runtime(self):
        # end time
        end_time = time.time()
        elapsed_time = end_time - self.start_time
        runtime = "{}:{}:{}".format(int(elapsed_time // 3600), 
                                    int((elapsed_time % 3600) // 60), 
                                    int(elapsed_time % 60))
        
        # set start time
        self.start_time = end_time
        
        return runtime
    
    def get_peak_memory(self):
        import os
        
        # Get current process ID
        pid = os.getpid()
        peak_memory = 0
        
        try:
            # Read memory usage from /proc/{pid}/status
            with open(f"/proc/{pid}/status", 'r') as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        # VmRSS is in kB
                        rss_kb = int(line.split()[1])
                        # Convert to MB
                        peak_memory = rss_kb / 1024
                        break
        except Exception as e:
            # Ignore errors, return 0 if failed
            pass
        
        return peak_memory
    
    def update_step(self, 
                    step_name : str,
                    state : str | StateEnum,
                    info : dict = {}):
        state = state.value if isinstance(state, StateEnum) else state
        
        runtime = self.get_runtime()
        peak_memory = self.get_peak_memory() - self.start_memory
        peak_memory = 0 if peak_memory < 0 else round(peak_memory, 3)
        
        for step_dict in self.workspace_step.subflow.get("steps", []):
            if step_dict.get("name") == step_name:
                step_dict["state"] = state
                step_dict["runtime"] = runtime
                step_dict["peak memory (mb)"] = peak_memory
                step_dict["info"] = info
                
                self.save()
                
                # update home page monitor
                self.workspace.home.update_monitor(step = self.workspace_step.name,
                                                   sub_step = step_name,
                                                   memory = str(peak_memory),
                                                   runtime = runtime)
                
                self.notify_subflow(step = self.workspace_step.name,
                                    subflow_path=self.workspace_step.subflow.get("path", ""),
                                    home_page=self.workspace.home.path)
                
                break