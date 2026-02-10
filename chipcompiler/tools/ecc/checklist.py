#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from chipcompiler.data import (
    Workspace, 
    WorkspaceStep, 
    Checklist, 
    StepEnum, 
    CheckState
)

class EccChecklist:
    def __init__(self, workspace : Workspace, workspace_step: WorkspaceStep):
        self.workspace = workspace
        self.workspace_step = workspace_step
        
        self.build_checklist()

    def build_checklist(self) -> list:
        checklist = Checklist(path=self.workspace_step.checklist.get("path", ""))
        step = StepEnum(self.workspace_step.name)
        match step:
            case StepEnum.FLOORPLAN:
                checklist.add(step=step.value, 
                              type="Area", 
                              item="check DIE area", 
                              state=CheckState.Unstart.value)
                
                # add to home page checklist
                self.workspace.home.update_checklist(step=step.value, 
                                                     type="Area", 
                                                     item="check DIE area", 
                                                     state=CheckState.Unstart.value)
            case StepEnum.NETLIST_OPT:
                pass
            case StepEnum.PLACEMENT:
                pass
            case StepEnum.CTS:
                pass
            case StepEnum.TIMING_OPT_DRV:
                pass
            case StepEnum.TIMING_OPT_HOLD:
                pass
            case StepEnum.TIMING_OPT_SETUP:
                pass
            case StepEnum.LEGALIZATION:
                pass
            case StepEnum.ROUTING:
                pass
            case StepEnum.FILLER:
                pass
            case StepEnum.DRC:
                pass
                
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