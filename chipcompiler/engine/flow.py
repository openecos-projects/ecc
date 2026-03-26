#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import os
import time
import logging
import traceback
from multiprocessing import Process
from threading import Thread

from chipcompiler.data import Workspace, WorkspaceStep, StateEnum, StepEnum, log_flow
from chipcompiler.engine import EngineDB
from chipcompiler.utility import track_process_memory
from chipcompiler.utility.log import redirect_stdio_to_file

logger = logging.getLogger(__name__)

def _run_step_in_subprocess(workspace: Workspace, workspace_step: WorkspaceStep) -> None:
    """
    Step subprocess entry point: redirect stdio to log file if configured,
    then execute the EDA tool step.
    """
    # Redirect stdout/stderr to the step's own log file.
    log_file = workspace_step.log.get("file", "")
    if log_file:
        log_file = os.path.abspath(log_file)
        try:
            os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
            redirect_stdio_to_file(log_file)
        except Exception:
            traceback.print_exc()

    step_tag = f"{workspace_step.name}({workspace_step.tool})"
    workspace.logger.info(f"[STEP] {step_tag} pid={os.getpid()} started")

    try:
        from chipcompiler.tools import run_step as run_tool_step
        result = run_tool_step(workspace=workspace, step=workspace_step)
        workspace.logger.info(f"[STEP] {step_tag} finished result={result}")
    except Exception:
        workspace.logger.error(f"[STEP] {step_tag} failed with exception")
        traceback.print_exc()


class EngineFlow:
    def __init__(self, workspace : Workspace):
        self.workspace = workspace
        self.workspace_steps = []
        self.db = None # db engine for this flow
        
        if self.workspace is not None:
            self.load()
    
    def build_default_steps(self):
        # Flow step sequences
        steps = []

        steps.append(self.init_flow_step(StepEnum.SYNTHESIS, "yosys", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.FLOORPLAN, "ecc", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.NETLIST_OPT, "ecc", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.PLACEMENT, "ecc", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.CTS, "ecc", StateEnum.Unstart))
        # steps.append(self.init_flow_step(StepEnum.TIMING_OPT_DRV, "ecc", StateEnum.Unstart))
        # steps.append(self.init_flow_step(StepEnum.TIMING_OPT_HOLD, "ecc", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.LEGALIZATION, "ecc", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.ROUTING, "ecc", StateEnum.Unstart))
        steps.append(self.init_flow_step(StepEnum.FILLER, "ecc", StateEnum.Unstart))
        # steps.append(self.init_flow_step(StepEnum.GDS, "klayout", StateEnum.Unstart))
        # steps.append(self.init_flow_step(StepEnum.SIGNOFF, "ecc", StateEnum.Unstart))
        
        self.workspace.flow.data = {"steps" : steps}
        
        self.save()
    
    def has_init(self):
        return True if self.workspace is not None and len(self.workspace.flow.data.get("steps", [])) > 0 else False
    
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
            "peak memory (mb)" : 0, # step peak memory
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
    
    def get_workspace_step(self,
                           name : str) -> WorkspaceStep | None:
        for workspace_step in self.workspace_steps:
            if workspace_step.name == name:
                return workspace_step
        
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
                 runtime : str=None,
                 peak_memory : float=None) -> bool:
        state_value = state.value if isinstance(state, StateEnum) else state
        for step in self.workspace.flow.data.get("steps", []):
            if step.get("name") == name and step.get("tool") == tool:
                step["state"] = state_value
                if runtime is not None:
                    step["runtime"] = runtime
                if peak_memory is not None:
                    step["peak memory (mb)"] = peak_memory

                self.save()
                return True
            
        return False
    
    def clear_states(self):
        from chipcompiler.data import StateEnum
        for step in self.workspace.flow.data.get("steps", []):
            step["state"] = StateEnum.Unstart.value
            step["runtime"] = ""
            step["peak memory (mb)"] = 0
            
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
        
    
    def run_steps(self, rerun=False) -> bool:
        """
        run all flow steps
        """
        
        self.workspace.home.reset() # reset home data before run steps
        
        for workspace_step in self.workspace_steps: 
            self.workspace.logger.log_section(f"{workspace_step.tool} - begin step - {workspace_step.name}")
            
            state = self.run_step(workspace_step, rerun)
            
            log_flow(workspace=self.workspace)
            self.workspace.logger.log_section(f"{workspace_step.tool} - end step - {workspace_step.name}")
            
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
                 workspace_step : WorkspaceStep | str,
                 rerun : bool = False) -> StateEnum:
        """
        run single step
        """
        if isinstance(workspace_step, str):
            workspace_step = self.get_workspace_step(workspace_step)
        if workspace_step is None:
            return StateEnum.Invalid
            
        step_tag = f"{workspace_step.name}({workspace_step.tool})"

        if not rerun and self.check_state(name=workspace_step.name,
                            tool=workspace_step.tool,
                            state=StateEnum.Success):
            self.workspace.logger.info("[SKIP] %s already succeeded", step_tag)
            return StateEnum.Success

        # set state ongoing
        start_time = time.time()
        self.set_state(name=workspace_step.name,
                       tool=workspace_step.tool,
                       state=StateEnum.Ongoing)

        # run step in a subprocess
        p = Process(target=_run_step_in_subprocess,
                    args=(self.workspace, workspace_step))
        p.start()
        step_log_file = workspace_step.log.get("file", "")
        logger.info("[DISPATCH] %s pid=%s log=%s", step_tag, p.pid,
                    os.path.abspath(step_log_file) if step_log_file else "N/A")

        # track peak memory in a background thread
        peak_memory_result = [0]
        def _track_memory():
            peak_memory_result[0] = track_process_memory(p.pid)
        tracker = Thread(target=_track_memory, daemon=True)
        tracker.start()

        p.join()
        tracker.join(timeout=1.0)

        # compute metrics
        peak_memory_mb = round(peak_memory_result[0] / 1024.0, 3)
        elapsed = time.time() - start_time
        runtime = f"{int(elapsed // 3600)}:{int((elapsed % 3600) // 60)}:{int(elapsed % 60)}"

        # determine and save state
        state = (StateEnum.Success
                 if self.check_step_result(workspace_step=workspace_step)
                 else StateEnum.Imcomplete)
        self.set_state(name=workspace_step.name,
                       tool=workspace_step.tool,
                       state=state,
                       runtime=runtime,
                       peak_memory=peak_memory_mb)
        self.workspace.logger.info("[RESULT] %s state=%s runtime=%s mem=%sMB exitcode=%s",
                    step_tag, state.value, runtime, peak_memory_mb, p.exitcode)

        # save layout snapshot on success
        if state == StateEnum.Success:
            from chipcompiler.tools import save_layout_image
            save_layout_image(workspace=self.workspace, step=workspace_step)

        return state
