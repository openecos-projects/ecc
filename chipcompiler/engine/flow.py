#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from chipcompiler.data import Workspace, WorkspaceStep, log_workspace
from chipcompiler.data import StateEnum, StepEnum
from chipcompiler.engine import EngineDB

class EngineFlow:
    def __init__(self, workspace : Workspace):
        self.workspace = workspace
        self.workspace_steps = []
        self.db = None # db engine for this flow
      
        self.load()
    
    def build_default_steps(self):
        # Flow step sequences
        steps = []

        steps.append(self.init_flow_step(StepEnum.SYNTHESIS, "yosys", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.FLOORPLAN, "iEDA", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.NETLIST_OPT, "iEDA", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.PLACEMENT, "iEDA", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.CTS, "iEDA", StateEnum.Unstart))
        # steps.append(self.init_flow_step(StepEnum.TIMING_OPT_DRV, "iEDA", StateEnum.Unstart))
        # steps.append(self.init_flow_step(StepEnum.TIMING_OPT_HOLD, "iEDA", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.LEGALIZATION, "iEDA", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.ROUTING, "iEDA", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.FILLER, "iEDA", StateEnum.Unstart))
        # steps.append(self.init_flow_step(StepEnum.GDS, "klayout", StateEnum.Unstart))
        # steps.append(self.init_flow_step(StepEnum.SIGNOFF, "innovus", StateEnum.Unstart))
        
        self.workspace.flow.data = {"steps" : steps}
        
        self.save()
    
    def has_init(self):
        return True if len(self.workspace.flow.data.get("steps", [])) > 0 else False
    
    def init_flow_step(self,
                  step : StepEnum | str,
                  tool : str,
                  state : str | StateEnum):
        step_value = step.value if isinstance(step, StepEnum) else step
        state_value = state.value if isinstance(state, StateEnum) else state
        return {
            "name" : step_value, # step name
            "tool" : tool, # eda tool name
            "state" : state_value, # step state
            "runtime" : "", # step run time
            "info" : {} # step additional infomation
        }
        
    def add_step(self,
                 step : StepEnum | str,
                 tool : str,
                 state : str | StateEnum):
        steps = self.workspace.flow.data.get("steps", [])
        steps.append(self.init_flow_step(step, tool, state))
        
        self.workspace.flow.data = {"steps" : steps}
        
        self.save()
    
    def load(self) -> bool:
        """
        load flow config json from workspace
        """
        from chipcompiler.utility import json_read
        self.workspace.flow.data = json_read(self.workspace.flow.path)
        if len(self.workspace.flow.data.get("steps", [])) <= 0:
            return False

        return True
        
    def save(self) -> bool:
        """
        save flow to workspace json
        """
        from chipcompiler.utility import json_write
        return json_write(self.workspace.flow.path, 
                          self.workspace.flow.data)
        
    def get_step(self,
                 name : str,
                 tool : str):
        for step in self.workspace.flow.data.get("steps", []):
            if step.get("name") == name and step.get("tool") == tool:
                return step
        
        return None
    
    def check_state(self,
                   name : str,
                   tool : str,
                   state : str | StateEnum):
        """
        return True if step state has been set
        """
        step = self.get_step(name, tool)
        state_value = state.value if isinstance(state, StateEnum) else state
        if step is not None \
            and step.get("state") == state_value:
            return True
            
        return False
        
    def set_state(self, 
                 name : str,
                 tool : str,
                 state : str | StateEnum,
                 runtime : str=None) -> bool:
        state_value = state.value if isinstance(state, StateEnum) else state
        for step in self.workspace.flow.data.get("steps", []):
            if step.get("name") == name and step.get("tool") == tool:
                step["state"] = state_value
                if runtime is not None:
                    step["runtime"] = runtime
                
                self.save()
                return True
            
        return False
    
    def clear_states(self):
        from chipcompiler.data import StateEnum
        for step in self.workspace.flow.data.get("steps", []):
            step["state"] = StateEnum.Unstart.value
            step["runtime"] = ""
            
        self.save()
        
    def is_flow_success(self):
        """
        check all steps success
        """
        from chipcompiler.data import StateEnum
        for step in self.workspace.flow.data.get("steps", []):
            if(step["state"] != StateEnum.Success.value):
                return False
            
        return True
    
    def check_step_result(self,
                          workspace_step : WorkspaceStep):
        """
        check step output exist
        """
        import os
        success = False
        match workspace_step.name:
            case StepEnum.SYNTHESIS.value:
                if os.path.exists(workspace_step.output.get("verilog", "")):
                    success = True
            case default:
                if os.path.exists(workspace_step.output.get("def", "")) and \
                    os.path.exists(workspace_step.output.get("verilog", "")) and \
                        os.path.exists(workspace_step.output.get("gds", "")):
                    success = True
        return success

    def create_step_workspaces(self):
        """
        create all step workspaces
        """
        pre_step = None
        for step in self.workspace.flow.data.get("steps", []):
            if pre_step is None:
                # use the origin def and verilog in workspace for the first step.
                input_def = self.workspace.design.origin_def
                input_verilog = self.workspace.design.origin_verilog
            else:
                # use the output def and verilog from last step.
                input_def = pre_step.output["def"]
                input_verilog = pre_step.output["verilog"]
                
            from chipcompiler.tools import create_step, run_step
            # create workspace step
            eda_step = create_step(workspace=self.workspace,
                                   step=step["name"],
                                   eda=step["tool"],
                                   input_def=input_def,
                                   input_verilog=input_verilog)
            # save workspace step
            if eda_step is not None:
                self.workspace_steps.append(eda_step)
                pre_step = eda_step
            else:
                # error create step, TBD
                pass
            
    def init_db_engine(self) -> bool:
        if len(self.workspace_steps) <= 0:
            return False
        
        if self.db is not None:
            return True
        
        # init engine step by last workpsace step data if all step run success
        workspace_step = self.workspace_steps[-1]
        for ws_step in self.workspace_steps:
            if not self.check_state(name=ws_step.name,
                                    tool=ws_step.tool,
                                    state=StateEnum.Success):
                # use the first unsuccess step to setup db engine
                workspace_step = ws_step
                                
        engine = EngineDB(workspace=self.workspace)
        if engine.create_db_engine(step=workspace_step):
            self.db = engine
            return True
        else:
            return False
        
    
    def run_steps(self) -> bool:
        """
        run all flow steps
        """
        for workspace_step in self.workspace_steps: 
            if self.check_state(name=workspace_step.name,
                                tool=workspace_step.tool,
                                state=StateEnum.Success):
                continue
            
            
                
            state = self.run_step(workspace_step)
            
            match(state):
                case StateEnum.Success:
                    continue
                case StateEnum.Invalid:
                    return False
                case StateEnum.Unstart:
                    return False
                case StateEnum.Imcomplete:
                    return False
                case StateEnum.Pending:
                    return False
                case StateEnum.Ongoing:
                    return False
        
        return True
            
    def run_step(self,
                 workspace_step : WorkspaceStep) -> StateEnum:
        """
        run single step
        """
        if self.check_state(name=workspace_step.name,
                            tool=workspace_step.tool,
                            state=StateEnum.Success):
            return StateEnum.Success
                        
        from chipcompiler.tools import create_step, run_step
        import time
        
        #set timer
        start_time = time.time()
        
        # set state ongoing
        self.set_state(name=workspace_step.name,
                       tool=workspace_step.tool,
                       state=StateEnum.Ongoing)
        
        # run steps
        from multiprocessing import Process
        p = Process(target=run_step, args=(self.workspace, workspace_step, ))
        p.start()
        p.join()
        
        # end time
        end_time = time.time()
        elapsed_time = end_time - start_time
        runtime = "{}:{}:{}".format(int(elapsed_time // 3600), 
                                    int((elapsed_time % 3600) // 60), 
                                    int(elapsed_time % 60))
        
        
        
        # save state
        state=StateEnum.Success if self.check_step_result(workspace_step=workspace_step) else StateEnum.Imcomplete
        self.set_state(name=workspace_step.name,
                       tool=workspace_step.tool,
                       state=state,
                       runtime=runtime)
        
        if state == StateEnum.Success:
            from chipcompiler.tools import save_layout_image
            save_layout_image(workspace=self.workspace,
                           step=workspace_step)
        
        return state