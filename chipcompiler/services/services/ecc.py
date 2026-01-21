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

from benchmark import  get_parameters

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
        self.flow = None
        
    def check_cmd(self, request: ECCRequest, cmd : CMDEnum):
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
    
    def create_workspace(self, request: ECCRequest) -> ECCResponse:
        # check cmd
        state, response = self.check_cmd(request, CMDEnum.create_workspace)
        if not state:
            return response 
            
        # get data
        data = request.data
 
        # check data
        
        # process cmd
        workspace = create_workspace(directory=data.get("directory", ""),
                                     pdk=data.get("pdk", ""),
                                     parameters=data.get("parameters", {}),
                                     origin_def=data.get("origin_def", ""),
                                     origin_verilog=data.get("origin_verilog", ""),
                                     input_filelist=data.get("rtl_list", ""))
        
        if workspace is None:
            return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.failed.value,
                data={},
                message = [f"create workspace failed : {data.get('directory', '')}"]
            )
        else:
            self.workspace = workspace
            self.build_flow()
            
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
        workspace = load_workspace(directory=data.get("directory", ""))
        
        if workspace is None:
            return ECCResponse(
                cmd=request.cmd,
                response=ResponseEnum.failed.value,
                data={},
                message = [f"load workspace failed : {data.get('directory', '')}"]
            )
        else:
            self.workspace = workspace
            self.build_flow()
            
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
        pass
    
    def build_flow(self):
        engine_flow = EngineFlow(workspace=self.workspace)
        if not engine_flow.has_init():
            steps = build_rtl2gds_flow()
            for step, tool, state in steps:
                engine_flow.add_step(step=step, tool=tool, state=state)
        if engine_flow.is_flow_success():
            return 
        engine_flow.create_step_workspaces()
