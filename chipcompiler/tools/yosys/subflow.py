#!/usr/bin/env python
from chipcompiler.data import StateEnum, Workspace, WorkspaceStep


class YosysSubFlow:
    def __init__(self, workspace : Workspace, workspace_step: WorkspaceStep):
        self.workspace = workspace
        self.workspace_step = workspace_step
        
        self.init_sub_flow()
    
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
        
    def update_step(self, 
                    step_name : str,
                    state : str | StateEnum,
                    runtime : str = "",
                    memory : float = 0,
                    info : dict = {}):
        state = state.value if isinstance(state, StateEnum) else state
        
        for step_dict in self.workspace_step.subflow.get("steps", []):
            if step_dict.get("name") == step_name:
                step_dict["state"] = state
                step_dict["runtime"] = runtime
                step_dict["peak memory (mb)"] = memory
                step_dict["info"] = info
        
        self.save()