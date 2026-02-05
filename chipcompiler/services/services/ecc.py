#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import os
import uuid
import threading

from chipcompiler.data import (
    create_workspace,
    load_workspace,
    StepEnum,
    StateEnum,
    PDK,
    get_pdk
)

from chipcompiler.engine import (
    EngineDB,
    EngineFlow
)

from chipcompiler.rtl2gds import build_rtl2gds_flow

from chipcompiler.services.schemas import (
    CMDEnum,
    ECCRequest, 
    ECCResponse, 
    ResponseEnum,
    DATA_TEMPLATE
    )

class ECCService:
    def __init__(self):
        self.workspace = None
        self.engine_flow = None

    @staticmethod
    def _normalize_rtl_list(rtl_list) -> list[str]:
        if not rtl_list:
            return []
        if isinstance(rtl_list, list):
            items = rtl_list
        elif isinstance(rtl_list, str):
            items = rtl_list.splitlines()
        else:
            items = [rtl_list]

        result = []
        seen = set()
        for item in items:
            path = str(item).strip()
            if not path or path in seen:
                continue
            seen.add(path)
            result.append(path)
        return result

    @staticmethod
    def _write_filelist(directory: str, rtl_paths: list[str]) -> str:
        os.makedirs(directory, exist_ok=True)
        filelist_path = os.path.join(directory, "filelist")
        with open(filelist_path, "w", encoding="utf-8") as f:
            for path in rtl_paths:
                if any(ch.isspace() for ch in path):
                    f.write(f"\"{path}\"\n")
                else:
                    f.write(f"{path}\n")
        return filelist_path
        
    def check_cmd(self, request: ECCRequest, cmd : CMDEnum):
        # print cmd
        # print(request)
        
        # check cmd
        if request.cmd != cmd.value:
            response = ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.failed.value,
                data={},
                message = [].append(f"requese cmd not match {request.cmd}")
            )
            
            return False, response
        
        return True, None
    
    def __build_flow(self):
        engine_flow = EngineFlow(workspace=self.workspace)
        if not engine_flow.has_init():
            steps = build_rtl2gds_flow()
            for step, tool, state in steps:
                engine_flow.add_step(step=step, tool=tool, state=state)
        else:
            engine_flow.create_step_workspaces()
        
        self.engine_flow = engine_flow
        
        if engine_flow.is_flow_success():
            return 
        engine_flow.create_step_workspaces()
    
    def create_workspace(self, request: ECCRequest) -> ECCResponse:
        # check cmd
        state, response = self.check_cmd(request, CMDEnum.create_workspace)
        if not state:
            return response 
            
        # get data
        data = request.data
 
        # check data
        
        # process cmd
        input_filelist = data.get("filelist", "")
        if not input_filelist:
            rtl_list = data.get("rtl_list", "")
            rtl_paths = self._normalize_rtl_list(rtl_list)
            if rtl_paths:
                try:
                    input_filelist = self._write_filelist(
                        directory=data.get("directory", ""),
                        rtl_paths=rtl_paths
                    )
                except Exception as e:
                    return ECCResponse(
                        cmd=request.cmd,
                        response=ResponseEnum.error.value,
                        data={},
                        message=[f"failed to create filelist from rtl_list: {e}"]
                    )
        
        try:
            workspace = create_workspace(directory=data.get("directory", ""),
                                         pdk=data.get("pdk", ""),
                                         parameters=data.get("parameters", {}),
                                         origin_def=data.get("origin_def", ""),
                                         origin_verilog=data.get("origin_verilog", ""),
                                         input_filelist=input_filelist)
        except Exception as e:
            return ECCResponse(
                        cmd=request.cmd,
                        response=ResponseEnum.error.value,
                        data={},
                        message=[f"create workspace failed : {data.get('directory', '')}, error info is {e}"]
                    )
        
        if workspace is None:
            return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.failed.value,
                data={},
                message = [f"create workspace failed : {data.get('directory', '')}"]
            )
        else:
            self.workspace = workspace
            self.__build_flow()
            
            response_data = {
                "directory" : data.get("directory", "")
            }
            return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.success.value,
                data=response_data,
                message = [f"create workspace success : {data.get('directory', '')}"]
            )
    
    def load_workspace(self, request: ECCRequest) -> ECCResponse:
        # check cmd
        state, response = self.check_cmd(request, CMDEnum.load_workspace)
        if not state:
            return response 
            
        # get data
        data = request.data
 
        # check data
        
        # process cmd
        try:
            workspace = load_workspace(directory=data.get("directory", ""))
        except Exception as e:
            return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.failed.value,
                data={},
                message = [f"load workspace failed : {data.get('directory', '')}, error info is {e}"]
            )
        
        if workspace is None:
            return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.failed.value,
                data={},
                message = [f"load workspace failed : {data.get('directory', '')}"]
            )
        else:
            self.workspace = workspace
            self.__build_flow()
            
            response_data = {
                "directory" : data.get("directory", "")
            }
            return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.success.value,
                data=response_data,
                message = [f"load workspace success : {data.get('directory', '')}"]
            )
    
    def delete_workspace(self, request: ECCRequest) -> ECCResponse:
        # check cmd
        state, response = self.check_cmd(request, CMDEnum.delete_workspace)
        if not state:
            return response 
        
        # get data
        data = request.data
        directory = data.get('directory', '')
 
        # check data
        if self.workspace is None \
            or self.workspace.directory != directory \
                or not os.path.exists(directory):
            return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.error.value,
                data={},
                message = [f"workspace not exist : {directory}"]
            )
            
        # process cmd
        self.engine_flow = None
        self.workspace = None
        try:
            import shutil
            shutil.rmtree(directory)
        except Exception as e:
            pass
            
        response_data = {
            "directory" : directory
        }
        return ECCResponse(
            cmd=request.cmd,
            response=ResponseEnum.success.value,
            data=response_data,
            message = [f"delete workspace success : {directory}"]
        )
        
    def rtl2gds(self, request: ECCRequest) -> ECCResponse:
        """
        启动 rtl2gds 流程
        
        生成 task_id 并立即返回，前端可订阅 SSE 事件流获取实时进度。
        流程在后台线程中执行。
        """
        # check cmd
        state, response = self.check_cmd(request, CMDEnum.rtl2gds)
        if not state:
            return response 
        
        # get data
        data = request.data
        rerun = data.get("rerun", False)
        
        # 生成 task_id
        task_id = str(uuid.uuid4())
        
        response_data = {
            "rerun": rerun,
            "task_id": task_id
        }

        # check data
        if self.workspace is None \
            or not os.path.exists(self.workspace.directory):
            return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.error.value,
                data=response_data,
                message = [f"workspace not exist : {self.workspace.directory}"]
            )
        
        if self.engine_flow is None:
            return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.error.value,
                data=response_data,
                message = [f"rtl2gds flow not exist : {self.workspace.directory}"]
            )
        
        # 在后台线程中执行流程
        def run_flow_async():
            from ..sse import event_manager
            
            try:
                if rerun:
                    self.engine_flow.clear_states()
                
                for workspace_step in self.engine_flow.workspace_steps:
                    step_name = workspace_step.name
                    
                    # 发送步骤开始通知
                    event_manager.notify_step_start(task_id, step_name)
                    
                    # 执行步骤
                    ecc_req = ECCRequest(
                        cmd="run_step",
                        data={
                            "step": step_name,
                            "rerun": rerun
                        }
                    )
                    step_response = self.run_step(ecc_req)
                    
                    if step_response.response == ResponseEnum.success.value:
                        # 发送数据就绪通知
                        event_manager.notify_data_ready(task_id, step_name, "info")
                        # 发送步骤完成通知
                        event_manager.notify_step_complete(task_id, step_name)
                    else:
                        # 发送错误通知
                        error_msg = step_response.message[0] if step_response.message else f"Step {step_name} failed"
                        event_manager.notify_error(task_id, step_name, error_msg)
                        # 发送任务失败通知
                        event_manager.notify_task_complete(task_id, f"Flow failed at step: {step_name}")
                        return
                
                # 发送任务完成通知
                event_manager.notify_task_complete(task_id, f"rtl2gds completed: {self.workspace.directory}")
                
            except Exception as e:
                event_manager.notify_error(task_id, None, str(e))
                event_manager.notify_task_complete(task_id, f"Flow failed with error: {e}")
        
        # 启动后台线程
        thread = threading.Thread(target=run_flow_async, daemon=True)
        thread.start()
        
        # 立即返回 task_id
        return ECCResponse(
            cmd=request.cmd,
            response=ResponseEnum.success.value,
            data=response_data,
            message=[f"rtl2gds started, task_id: {task_id}"]
        )
        
    def run_step(self, request: ECCRequest) -> ECCResponse:
        # check cmd
        state, response = self.check_cmd(request, CMDEnum.run_step)
        if not state:
            return response 
        
        # get data
        data = request.data
        step = data.get("step", "")
        rerun = data.get("rerun", "")
        
        response_data = {
            "step" : step,
            "state" : "Unstart"
        }
 
        # check data
        if self.workspace is None \
            or not os.path.exists(self.workspace.directory):
            return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.error.value,
                data=response_data,
                message = [f"workspace not exist : {self.workspace.directory}"]
            )
            
        # process cmd
        state = StateEnum.Unstart
        try:
            state = self.engine_flow.run_step(step, rerun)
        except Exception as e:
            state = StateEnum.Imcomplete
            pass
        
        response_data["state"] = state.value
        
        if StateEnum.Success == state:
            return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.success.value,
                data=response_data,
                message = [f"run step {step} success : {self.workspace.directory}"]
            )
        else:
            return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.failed.value,
                data=response_data,
                message = [f"run step {step} failed with state {state.value} : {self.workspace.directory}"]
            )
            
    def get_info(self, request: ECCRequest) -> ECCResponse:
        # check cmd
        state, response = self.check_cmd(request, CMDEnum.get_info)
        if not state:
            return response 
        
        # get data
        data = request.data
        step = data.get("step", "")
        id = data.get("id", "")
        
        
        response_data = {
            "step" : step,
            "id" : id,
            "info" : {}
        }
 
        # check data
        if self.workspace is None \
            or not os.path.exists(self.workspace.directory):
            return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.error.value,
                data=response_data,
                message = [f"workspace not exist : {self.workspace.directory}"]
            )
            
        # process cmd
        try:
            # build information
            from .info import get_step_info
            info = get_step_info(workspace=self.workspace,
                                 step=self.engine_flow.get_workspace_step(step),
                                 id=id)
            
            if len(info) == 0:
                return ECCResponse(
                    cmd=request.cmd,
                    response=ResponseEnum.warning.value,
                    data=response_data,
                    message = [f"no information for step {step} : {self.workspace.directory}"]
                )
            else:
                response_data["info"] = info
        except Exception as e:
            return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.error.value,
                data=response_data,
                message = [f"get information error for step {step} : {e}"]
            )
        
        return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.success.value,
                data=response_data,
                message = [f"get information success : {step} - {id}"]
            )
