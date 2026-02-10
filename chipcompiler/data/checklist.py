#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import os
from enum import Enum
from chipcompiler.utility import json_read, json_write

class CheckState(Enum):
    """checklist state"""
    Unstart = "Unstart" # checked unstart
    Success = "Success" # checked success
    Failed = "Failed" # checked Failed
    Warning = "Warning" # checked Warning
    
class Checklist:
    """
    Checklist information
    """
    def __init__(self, path : str):
        self.path : str = path # checklist file path
        self.header = ["step", "type", "item", "state"]
        self.data : dict = {} # checklist data
        
        if os.path.exists(self.path):
            self.data = json_read(self.path)
        else:
            self.save()
            
        self.data = json_read(self.path)
        
        if len(self.data) == 0:
            self.data["path"] = path
            self.data["checklist"] = []
            
    def save(self):
        json_write(self.path, self.data)
        
    def add(self,
            step : str, 
            type : str,
            item : str,
            state : str):
        # check if exist
        for check_item in self.data.get("checklist", []):
            if check_item["step"] == step and check_item["type"] == type and check_item["item"] == item:
                return
        
        # add to checklist    
        check_item = {
            "step" : step,
            "type" : type,
            "item" : item,
            "state" : state
        }
        self.data["checklist"].append(check_item)
        
        self.save()
        
    def update(self,
               step : str, 
               type : str,
               item : str,
               state : str | CheckState):
        # check if exist
        for check_item in self.data.get("checklist", []):
            if check_item["step"] == step and check_item["type"] == type and check_item["item"] == item:
                check_item["state"] = state.value if isinstance(state, CheckState) else state
                self.save()
                return
        
        # add to checklist    
        self.add(step=step, 
                 type=type, 
                 item=item, 
                 state=state)
        