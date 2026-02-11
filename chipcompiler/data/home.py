#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import os
from chipcompiler.utility import json_read, json_write
from .checklist import Checklist

# home_json = {
#    "parameters" : "",
#     "flow" : "",
#     "layout" : "",
#     "GDS merge" : "",
#     "monitor" : {
#         "step" : [],
#         "memory" : [],
#         "runtime" : [],
#         "instance" : [],
#         "frequency" : []
#     },
#     "metrics":{
#         "instance dist." : "",
#         "layer dist." : "",
#         "net pin dist." : "",
#         "drc type dist." : "",
#         "drc layer dist." : "",
#         "CTS skew map" : ""
#     },
#     "checklist" : ""
# }
home_json = {
    "parameters" : "",
    "flow" : "",
    "layout" : "",
    "GDS merge" : "",
    "checklist" : "",
    "metrics":{},
    "monitor" : {
        "step" : [],
        "memory" : [],
        "runtime" : [],
        "instance" : [],
        "frequency" : []
    }
}

class HomeData:
    """
    Home data information
    """
    def __init__(self, path : str = ""):
        self.path : str = path # home data file path
        self.data : dict = {} # home data
            
    def init(self, path : str):
        self.path : str = path
        self.data : dict = {}
    
        if os.path.exists(self.path):
            self.data = json_read(self.path)
        else:
            self.data = home_json.copy()
            self.save()
            
    def reload(self):
        self.data = json_read(self.path)
        
    def reset(self):
        self.data = home_json.copy()
        self.save()
            
    def save(self):
        json_write(self.path, self.data)
        
    def set_parameters(self, path : str):
        self.reload()
        self.data["parameters"] = path
        self.save()
        
    def set_flow(self, path : str):
        self.reload()
        self.data["flow"] = path
        self.save()
    
    def set_layout(self, path : str):
        self.reload()
        self.data["layout"] = path
        self.save()
    
    def set_gds_merge(self, path : str):
        self.reload()
        self.data["GDS merge"] = path
        self.save()
        
    def set_metrics_inst_dist(self, image_path : str):
        self.reload()
        self.data["metrics"]["instances dist."] = image_path
        self.save()
        
    def set_metrics_layer_dist(self, image_path : str):
        self.reload()
        self.data["metrics"]["layer dist."] = image_path
        self.save()
        
    def set_metrics_net_pin_dist(self, image_path : str):
        self.reload()
        self.data["metrics"]["net pin dist."] = image_path
        self.save()
        
    def set_metrics_drc_type_dist(self, image_path : str):
        self.reload()
        self.data["metrics"]["drc type dist."] = image_path
        self.save()
        
    def set_metrics_drc_layer_dist(self, image_path : str):
        self.reload()
        self.data["metrics"]["drc layer dist."] = image_path
        self.save()
        
    def set_metrics_cts_skew_map(self, image_path : str):
        self.reload()
        self.data["metrics"]["CTS skew map"] = image_path
        self.save()
    
    def update_monitor(self,
                       step : str,
                       sub_step : str,
                       memory : str,
                       runtime : str,
                       instance : int=0,
                       frequency : float=0.0):
        self.reload()
        
        # if not set, use last value
        if instance == 0:
            instance = self.data["monitor"]["instance"][-1] if len(self.data["monitor"]["instance"]) > 0 else 0
        if frequency == 0.0:
            frequency = self.data["monitor"]["frequency"][-1] if len(self.data["monitor"]["frequency"]) > 0 else 0.0
        
        step_name = f"{step} - {sub_step}"
        for i, existing_step in enumerate(self.data["monitor"]["step"]):
            if existing_step == step_name:
                self.data["monitor"]["memory"][i] = memory
                self.data["monitor"]["runtime"][i] = runtime
                self.data["monitor"]["instance"][i] = instance
                self.data["monitor"]["frequency"][i] = frequency
                self.save()
                return
        
        self.data["monitor"]["step"].append(step_name)
        self.data["monitor"]["memory"].append(memory)
        self.data["monitor"]["runtime"].append(runtime)
        self.data["monitor"]["instance"].append(instance)
        self.data["monitor"]["frequency"].append(frequency)
        
        self.save()
        
    def set_checklist(self, checklist_path : str):
        self.data["checklist"] = checklist_path
        
        if not os.path.exists(checklist_path):
            Checklist(path=checklist_path).save()
        
        self.save()
            
    def get_checklist_header(self):
        return Checklist(path=self.data.get("checklist", "")).header
        
    def update_checklist(self,
                         step : str, 
                         type : str,
                         item : str,
                         state : str):
        checklist = Checklist(path=self.data.get("checklist", ""))
        checklist.update(step=step, type=type, item=item, state=state)