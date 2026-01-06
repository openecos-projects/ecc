#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from chipcompiler.data import Workspace, WorkspaceStep
from chipcompiler.tools.klayout.utility import is_eda_exist
from chipcompiler.tools.klayout.module import KlayoutModule

def run_step():
    pass

def save_gds_image(workspace: Workspace,
                     step: WorkspaceStep) -> bool:
    """"""
    if not is_eda_exist():
        return False
    
    klayout_module = KlayoutModule(workspace=workspace,
                                   step=step)
    
    return klayout_module.save_layout_image()
    