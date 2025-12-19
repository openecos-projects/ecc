#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from chipcompiler.workspaces import Workspace, WorkspaceStep

class IEDAEngine:
    def __init__(self, workspace: Workspace, step: WorkspaceStep):
        try:
            import ieda_py as ieda
        except ImportError:
            raise ImportError("iEDA tool is not installed or not found.")
    
        self.ieda = ieda
        self.workspace = workspace
        self.step = step

    def get_ieda(self):
        return self.ieda
    
    def set_net(self, net_name: str, net_type: str):
        return self.ieda.set_net(net_name=net_name, net_type=net_type)

