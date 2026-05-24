#!/usr/bin/env python
import os
from copy import deepcopy

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
#         "layer via dist." : "",
#         "layer wire dist." : "",
#         "pin dist." : "",
#         "drc dist." : "",
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

_monitor_keys = ("step", "memory", "runtime", "instance", "frequency")

def _default_home_data() -> dict:
    return deepcopy(home_json)

def _normalize_home_data(data: dict) -> tuple[dict, bool]:
    normalized = _default_home_data()
    changed = not isinstance(data, dict)

    if isinstance(data, dict):
        for key, value in data.items():
            normalized[key] = value

    if not isinstance(normalized.get("metrics"), dict):
        normalized["metrics"] = {}
        changed = True

    if not isinstance(normalized.get("monitor"), dict):
        normalized["monitor"] = _default_home_data()["monitor"]
        changed = True

    for key in home_json:
        if key not in normalized:
            normalized[key] = _default_home_data()[key]
            changed = True

    for key in _monitor_keys:
        if not isinstance(normalized["monitor"].get(key), list):
            normalized["monitor"][key] = []
            changed = True

    if isinstance(data, dict) and normalized != data:
        changed = True

    return normalized, changed

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
            self.data, changed = _normalize_home_data(json_read(self.path))
            if changed:
                self.save()
        else:
            self.data = _default_home_data()
            self.save()
            
    def reload(self):
        self.data, changed = _normalize_home_data(json_read(self.path))
        if changed:
            self.save()
        
    def reset(self):
        self.data = _default_home_data()
        self.save()
            
    def save(self):
        self.data, _ = _normalize_home_data(self.data)
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
        
    def set_metrics_layer_via_dist(self, image_path : str):
        self.reload()
        self.data["metrics"]["layer via dist."] = image_path
        self.save()
        
    def set_metrics_layer_wire_dist(self, image_path : str):
        self.reload()
        self.data["metrics"]["layer wire dist."] = image_path
        self.save()
        
    def set_metrics_pin_dist(self, image_path : str):
        self.reload()
        self.data["metrics"]["pin dist."] = image_path
        self.save()
        
    def set_metrics_drc_dist(self, image_path : str):
        self.reload()
        self.data["metrics"]["drc dist."] = image_path
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
            instance_values = self.data["monitor"]["instance"]
            instance = instance_values[-1] if len(instance_values) > 0 else 0
        if frequency == 0.0:
            frequency_values = self.data["monitor"]["frequency"]
            frequency = frequency_values[-1] if len(frequency_values) > 0 else 0.0
        
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
