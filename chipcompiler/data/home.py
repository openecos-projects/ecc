#!/usr/bin/env python
import fcntl
import os
from collections.abc import Callable
from contextlib import contextmanager
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
_monitor_defaults = {
    "step": "",
    "memory": "",
    "runtime": "",
    "instance": 0,
    "frequency": 0.0,
}

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

    monitor_length = max(len(normalized["monitor"][key]) for key in _monitor_keys)
    for key in _monitor_keys:
        missing_count = monitor_length - len(normalized["monitor"][key])
        if missing_count > 0:
            normalized["monitor"][key].extend([_monitor_defaults[key]] * missing_count)
            changed = True

    if isinstance(data, dict) and normalized != data:
        changed = True

    return normalized, changed

def _read_normalized_home_data(path: str) -> tuple[dict, bool]:
    return _normalize_home_data(json_read(path))

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
            self._repair_or_reload()
        else:
            self.reset()
            
    def reload(self):
        self._repair_or_reload()
        
    def reset(self):
        self._update(lambda data: data.clear() or data.update(_default_home_data()))
            
    def save(self):
        source = self.data
        self._update(lambda data: data.clear() or data.update(source), force=True)

    @contextmanager
    def _locked(self):
        lock_path = f"{self.path}.lock"
        with open(lock_path, "a") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _update(self, mutator: Callable[[dict], bool | None], force: bool = False) -> None:
        with self._locked():
            data, repaired = _read_normalized_home_data(self.path)
            before = deepcopy(data)
            mutated = mutator(data)
            data, normalized = _normalize_home_data(data)
            changed = force or repaired or normalized or mutated is True or data != before
            if changed:
                json_write(self.path, data)
            self.data = data

    def _repair_or_reload(self) -> None:
        self._update(lambda data: False)

    def _set_path_value(self, key: str, path: str):
        def mutator(data: dict) -> bool:
            if data.get(key) == path:
                return False
            data[key] = path
            return True

        self._update(mutator)
        
    def set_parameters(self, path : str):
        self._set_path_value("parameters", path)
        
    def set_flow(self, path : str):
        self._set_path_value("flow", path)
    
    def set_layout(self, path : str):
        self._set_path_value("layout", path)
    
    def set_gds_merge(self, path : str):
        self._set_path_value("GDS merge", path)

    def _set_metric(self, key: str, image_path: str):
        def mutator(data: dict) -> bool:
            if data["metrics"].get(key) == image_path:
                return False
            data["metrics"][key] = image_path
            return True

        self._update(mutator)
        
    def set_metrics_inst_dist(self, image_path : str):
        self._set_metric("instances dist.", image_path)
        
    def set_metrics_layer_via_dist(self, image_path : str):
        self._set_metric("layer via dist.", image_path)
        
    def set_metrics_layer_wire_dist(self, image_path : str):
        self._set_metric("layer wire dist.", image_path)
        
    def set_metrics_pin_dist(self, image_path : str):
        self._set_metric("pin dist.", image_path)
        
    def set_metrics_drc_dist(self, image_path : str):
        self._set_metric("drc dist.", image_path)
        
    def set_metrics_cts_skew_map(self, image_path : str):
        self._set_metric("CTS skew map", image_path)
    
    def update_monitor(self,
                       step : str,
                       sub_step : str,
                       memory : str,
                       runtime : str,
                       instance : int=0,
                       frequency : float=0.0):
        def mutator(data: dict) -> bool:
            target_instance = instance
            target_frequency = frequency

            # if not set, use last value
            if target_instance == 0:
                instance_values = data["monitor"]["instance"]
                target_instance = instance_values[-1] if len(instance_values) > 0 else 0
            if target_frequency == 0.0:
                frequency_values = data["monitor"]["frequency"]
                target_frequency = frequency_values[-1] if len(frequency_values) > 0 else 0.0

            step_name = f"{step} - {sub_step}"
            for i, existing_step in enumerate(data["monitor"]["step"]):
                if existing_step == step_name:
                    changed = (
                        data["monitor"]["memory"][i] != memory
                        or data["monitor"]["runtime"][i] != runtime
                        or data["monitor"]["instance"][i] != target_instance
                        or data["monitor"]["frequency"][i] != target_frequency
                    )
                    data["monitor"]["memory"][i] = memory
                    data["monitor"]["runtime"][i] = runtime
                    data["monitor"]["instance"][i] = target_instance
                    data["monitor"]["frequency"][i] = target_frequency
                    return changed

            data["monitor"]["step"].append(step_name)
            data["monitor"]["memory"].append(memory)
            data["monitor"]["runtime"].append(runtime)
            data["monitor"]["instance"].append(target_instance)
            data["monitor"]["frequency"].append(target_frequency)
            return True

        self._update(mutator)
        
    def set_checklist(self, checklist_path : str):
        if not os.path.exists(checklist_path):
            Checklist(path=checklist_path).save()

        self._set_path_value("checklist", checklist_path)
            
    def get_checklist_header(self):
        return Checklist(path=self.data.get("checklist", "")).header
        
    def update_checklist(self,
                         step : str, 
                         type : str,
                         item : str,
                         state : str,
                         info : str = ""):
        checklist = Checklist(path=self.data.get("checklist", ""))
        checklist.update(step=step, type=type, item=item, state=state, info=info)
