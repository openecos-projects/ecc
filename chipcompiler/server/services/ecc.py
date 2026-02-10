#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import os

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

from chipcompiler.server.schemas import (
    CMDEnum,
    ECCRequest, 
    ECCResponse, 
    ResponseEnum
    )

from chipcompiler.server.sse import server_notify
notify_service = server_notify()

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
        """
        "request" : {
            "directory" : "",
            "pdk" : "",
            "parameters" : {},
            "origin_def" : "",
            "origin_verilog" : "",
            "filelist" : "",
            "rtl_list" : ""
        },
        "response" : {
            "directory" : ""
        }
        """
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
            
            # 设置 notify_service 的 workspace_id
            notify_service.set_workspace(workspace.directory)
            
            response_data = {
                "directory" : data.get("directory", ""),
                "workspace_id": workspace.directory  # 前端用于订阅 SSE
            }
            return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.success.value,
                data=response_data,
                message = [f"create workspace success : {data.get('directory', '')}"]
            )
    
    def load_workspace(self, request: ECCRequest) -> ECCResponse:
        """
        "request" : {
            "directory" : ""
        },
        "response" : {
            "directory" : ""
        }
        """
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
            
            # 设置 notify_service 的 workspace_id
            notify_service.set_workspace(workspace.directory)
            
            response_data = {
                "directory" : data.get("directory", ""),
                "workspace_id": workspace.directory  # 前端用于订阅 SSE
            }
            return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.success.value,
                data=response_data,
                message = [f"load workspace success : {data.get('directory', '')}"]
            )
    
    def delete_workspace(self, request: ECCRequest) -> ECCResponse:
        """
        "request" : {
            "directory" : ""
        },
        "response" : {
            "directory" : ""
        }
        """
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
        
        # 清除 notify_service 的 workspace_id
        notify_service.clear_workspace()
        
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
        "request" : {
            "rerun" : False
        },
        "response" : {
            "rerun" : False
        }
        """
        # check cmd
        state, response = self.check_cmd(request, CMDEnum.rtl2gds)
        if not state:
            return response 
        
        # get data
        data = request.data
        
        response_data = {
            "rerun" : data.get("rerun", False)
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
            
        # process cmd
        failed_step = None
        try:
            if data.get("rerun", False):
                self.engine_flow.clear_states()
            
            for workspace_step in self.engine_flow.workspace_steps:
                ecc_req = ECCRequest(
                cmd = "run_step",
                data = {
                        "step" : workspace_step.name,
                        "rerun" : data.get("rerun", False)
                    }
                )
                # get response for each step
                # TBD, need to send response back to gui
                step_response = self.run_step(ecc_req)
                if step_response.response != ResponseEnum.success.value:
                    failed_step = workspace_step.name
                    break
                else: 
                    notify_service.notify_step(step=workspace_step.name,
                                               step_path=self.workspace.flow.path)
            # self.engine_flow.run_steps()
        except Exception as e:
            return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.error.value,
                data=response_data,
                message = [f"run rtl2gds failed : {e}"]
            )
        
        if failed_step is None:
            return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.success.value,
                data=response_data,
                message = [f"run rtl2gds success : {self.workspace.directory}"]
            )
        else:
            return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.failed.value,
                data=response_data,
                message = [f"run rtl2gds failed in step : {failed_step}"]
            )

    def run_step(self, request: ECCRequest) -> ECCResponse:
        """
        "request" : {
            "step" : "",
            "rerun" : False
        },
        "response" : {
            "step" : "",
            "state" : "Unstart"
        }
        """
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
        """
        get information by step (defined by StepEnum) and id (defined by InfoEnum)
        "request" : {
            "step" : "",
            "id" : ""
        },
        "response" : {
            "step" : "",
            "id" : "",
            "info" : {}
        }
        """
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
        
    def get_home_page(self, request: ECCRequest) -> ECCResponse:
        """
        "request" : {},
        "response" : {
            "path" : ""
        }
        """
        # check cmd
        state, response = self.check_cmd(request, CMDEnum.home_page)
        if not state:
            return response 
            
        # get data
        data = request.data
 
        # check data
        
        # process cmd
        if os.path.exists(self.workspace.home.path):
            response_data = {
                "path" : self.workspace.home.path
            }
            return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.success.value,
                data=response_data,
                message = [f"build home page success : {self.workspace.home.path}"]
            )
        else:
            return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.failed.value,
                data={},
                message = [f"build home page failed : {self.workspace.home.path}"]
            )