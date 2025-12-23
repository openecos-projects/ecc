#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import sys
import os
    
current_dir = os.path.dirname(os.path.abspath(__file__))
    
from chipcompiler.workspaces import WorkspaceStep, Workspace, Parameters


def run_step(workspace: Workspace,
             step: WorkspaceStep) -> bool:
    from chipcompiler.tools.iEDA.utility import is_eda_exist
    if not is_eda_exist():
        return False
    
    from chipcompiler.tools.iEDA.engine import IEDAEngine
    eda_inst = IEDAEngine()
    
    return True

def get_eda() -> None:
    pass