#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import os
from enum import Enum
from chipcompiler.utility import json_read, json_write

class CheckState(Enum):
    """checklist state"""
    Unstart = "Unstart" # checked unstart
    Passed = "Passed" # checked passed
    Failed = "Failed" # checked Failed
    Warning = "Warning" # checked Warning
    
class Checklist:
    """
    Checklist information
    """
    def __init__(self, path : str):
        self.path : str = path # checklist file path
        self.header = ["step", "type", "item", "state", "info"]
        self.data : dict = {} # checklist data
        
        if os.path.exists(self.path):
            self.data = json_read(self.path)
        else:
            self.save()
            
        self.data = json_read(self.path)
        
        if len(self.data) == 0:
            self.data["path"] = path
            self.data["checklist"] = []
        else:
            for check_item in self.data.get("checklist", []):
                check_item.setdefault("info", "")
            
    def save(self):
        json_write(self.path, self.data)

    def state_value(self,
                    state : str | CheckState) -> str:
        return state.value if isinstance(state, CheckState) else state

    def check_info(self,
                   state : str | CheckState,
                   item : str,
                   info : str = "") -> str:
        state_value = self.state_value(state)
        if info or state_value not in (CheckState.Failed.value, CheckState.Warning.value):
            return info

        return f"{state_value}: {item} check needs attention"

    def state_statistics(self) -> dict:
        statistics = {
            state.value: 0
            for state in CheckState
        }
        checklist = self.data.get("checklist", [])

        for check_item in checklist:
            state = check_item.get("state", "")
            if state in statistics:
                statistics[state] += 1

        return {
            "total": len(checklist),
            **statistics,
        }
        
    def add(self,
            step : str, 
            type : str,
            item : str,
            state : str,
            info : str = ""):
        # check if exist
        for check_item in self.data.get("checklist", []):
            if check_item["step"] == step and check_item["type"] == type and check_item["item"] == item:
                return
        
        # add to checklist    
        check_item = {
            "step" : step,
            "type" : type,
            "item" : item,
            "state" : self.state_value(state),
            "info" : self.check_info(state=state, item=item, info=info)
        }
        self.data["checklist"].append(check_item)
        
        self.save()
        
    def update(self,
               step : str, 
               type : str,
               item : str,
               state : str | CheckState,
               info : str = ""):
        # check if exist
        for check_item in self.data.get("checklist", []):
            if check_item["step"] == step and check_item["type"] == type and check_item["item"] == item:
                check_item["state"] = self.state_value(state)
                check_item["info"] = self.check_info(state=state, item=item, info=info)
                self.save()
                return
        
        # add to checklist    
        self.add(step=step, 
                 type=type, 
                 item=item, 
                 state=self.state_value(state),
                 info=info)
