#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from chipcompiler.data import (
    Workspace, WorkspaceStep, Checklist, CheckState
)

class YosysChecklist:
    def __init__(self, workspace : Workspace, workspace_step: WorkspaceStep):
        self.workspace = workspace
        self.workspace_step = workspace_step
        
        self.build_checklist()
    

    def build_checklist(self) -> list:
        checklist = Checklist(path=self.workspace_step.checklist.get("path", ""))
                
        self.workspace_step.checklist["checklist"] = checklist.data
    
    def save(self) -> bool:
        checklist = Checklist(path=self.workspace_step.checklist.get("path", ""))
        return checklist.save()
        
    def update_item(self, 
                    step : str, 
                    type : str,
                    item : str,
                    state : str | CheckState):
        checklist = Checklist(path=self.workspace_step.checklist.get("path", ""))
        checklist.update(step=step, 
                         type=type, 
                         item=item, 
                         state=state)
        
    def check(self):
        pass