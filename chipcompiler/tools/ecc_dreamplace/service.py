#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import os
from chipcompiler.data import (
    Workspace, 
    WorkspaceStep, 
    StepEnum
)

from chipcompiler.utility import dict_to_str

    
def get_step_info(workspace: Workspace, 
                  step: WorkspaceStep,
                  id : str) -> dict:
    """
    get step info by step and command id, return dict as resource definition
    """
    from chipcompiler.tools.ecc import get_step_info as ecc_get_step_info
    step_info = {}
    

    step_info = ecc_get_step_info(workspace=workspace,
                                  step=step,
                                  id=id)
    
    workspace.logger.log_section(f"[ecc dreamplace] get step info, id = {id}")
    workspace.logger.info(f"{dict_to_str(step_info)}")
    
    return step_info