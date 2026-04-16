#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import os
from chipcompiler.data import (
    Workspace, 
    WorkspaceStep, 
    StepEnum
)

from chipcompiler.tools.ecc.metrics import build_step_metrics

from chipcompiler.utility import json_read, dict_to_str
    
def get_step_info(workspace: Workspace, 
                  step: WorkspaceStep,
                  id : str) -> dict:
    """
    get step info by step and command id, return dict as resource definition
    """
    step_info = {}
    
    match id:
        case "views":
            step_info = build_views(workspace=workspace, step=step)
        case "layout":
            step_info = build_layout(workspace=workspace, step=step)
        case "metrics":
            step_info = build_metrics(workspace=workspace, step=step)
        case "subflow":
            step_info = build_subflow(workspace=workspace, step=step)
        case "analysis":
            step_info = build_analysis(workspace=workspace, step=step)
        case "maps":
            step_info = build_maps(workspace=workspace, step=step)
        case "checklist":
            step_info = build_checklist(workspace=workspace, step=step)
        case "sta":
            step_info = build_sta(workspace=workspace, step=step)
        case "config":
            step_info = build_config(workspace=workspace, step=step)

    workspace.logger.log_section(f"[ecc] get step info, id = {id}")
    workspace.logger.info(f"{dict_to_str(step_info)}")

    return step_info

def build_views(workspace: Workspace, 
                step: WorkspaceStep) -> dict:
    metrics = build_step_metrics(workspace=workspace,
                                 step=step)
    
    info = {
        "image" : step.output.get("image", ""),
        "json" : step.output.get("json", ""),
        "metrics" : metrics.path,
        "information" : {}
    }
    
    return info

def build_metrics(workspace: Workspace, 
                  step: WorkspaceStep) -> dict:
    metrics = build_step_metrics(workspace=workspace,
                                 step=step)
    info = {
        "metrics" : metrics.path
    }
    
    return info

def build_layout(workspace: Workspace, 
                 step: WorkspaceStep) -> dict:
    info = {
        "image" : step.output.get("image", ""),
        "json" : step.output.get("json", "")
    }
    
    return info

def build_subflow(workspace: Workspace, 
                  step: WorkspaceStep) -> dict:       
    info = {
        "path" : step.subflow.get("path", "")
    }
    
    return info

def build_config(workspace: Workspace,
                 step: WorkspaceStep) -> dict:
    cfg = step.config or {}
    info = {
        "flow": cfg.get("flow", ""),
    }
    if not info["flow"] and info["dir"]:
        info["flow"] = os.path.join(info["dir"], "flow_config.json")
    elif not info["flow"] and step.directory:
        info["flow"] = os.path.join(step.directory, "config", "flow_config.json")
    return info

def build_analysis(workspace: Workspace, 
                   step: WorkspaceStep) -> dict:          
    info = {
        "metrics" : step.analysis.get('metrics', ""),
        "statis" : step.analysis.get('statis_csv', ""),
        "data summary" : step.feature.get('db', ""),
        "step feature" : step.feature.get('step', ""),
        "step report" : step.report.get('db', "")
    }
    
    return info

def build_maps(workspace: Workspace, 
               step: WorkspaceStep) -> dict:     
    info = {}
     
    match StepEnum(step.name):
        case StepEnum.FLOORPLAN:
            pass
        case StepEnum.NETLIST_OPT:
            pass
        case StepEnum.PLACEMENT:
            info.update(build_maps_congestion(workspace, step))
            info.update(build_maps_density(workspace, step))
        case StepEnum.CTS:
            info.update(build_maps_congestion(workspace, step))
            info.update(build_maps_density(workspace, step))
        case StepEnum.TIMING_OPT_DRV:
            pass
        case StepEnum.TIMING_OPT_HOLD:
            pass
        case StepEnum.LEGALIZATION:
            pass
        case StepEnum.ROUTING:
            pass
        case StepEnum.DRC:
            pass
        case StepEnum.FILLER:
            pass
    
    return info

def csv2png(csv : str) -> str:
    return csv.replace(".csv", ".png")
    
def build_maps_congestion(workspace: Workspace, 
                          step: WorkspaceStep) -> dict:     
    info = {}
    
    json_data = json_read(step.feature.get("map", ""))
    if len(json_data) > 0:
        json_cong = json_data.get("Congestion", {})
        json_map = json_cong.get("map", {})
        json_overflow = json_cong.get("overflow", {})
        json_util = json_cong.get("utilization", {})
        
        # egr maps
        info["egr-horizontal" ] = {
            "path" : csv2png(json_map.get("egr", {}).get("horizontal", "")),
            "info" : [
                ""
            ]
        }
        
        info["egr-vertical" ] = {
            "path" : csv2png(json_map.get("egr", {}).get("vertical", "")),
            "info" : [
                ""
            ]
        }
        
        info["egr-union" ] = {
            "path" : csv2png(json_map.get("egr", {}).get("union", "")),
            "info" : [
                ""
            ]
        }
        
        # lut rudy map
        info["lutrudy-horizontal" ] = {
            "path" : csv2png(json_map.get("lutrudy", {}).get("horizontal", "")),
            "info" : [
                f"max utilization : {json_util.get('lutrudy', {}).get('max', {}).get('horizontal', 0)}",
                f"top average : {json_util.get('lutrudy', {}).get('top_average', {}).get('horizontal', 0)}"
            ]
        }
        
        info["lutrudy-vertical" ] = {
            "path" : csv2png(json_map.get("lutrudy", {}).get("vertical", "")),
            "info" : [
                f"max utilization : {json_util.get('lutrudy', {}).get('max', {}).get('vertical', 0)}",
                f"top average : {json_util.get('lutrudy', {}).get('top_average', {}).get('vertical', 0)}"
            ]
        }
        
        info["lutrudy-union" ] = {
            "path" : csv2png(json_map.get("lutrudy", {}).get("union", "")),
            "info" : [
                f"max utilization : {json_util.get('lutrudy', {}).get('max', {}).get('union', 0)}",
                f"top average : {json_util.get('lutrudy', {}).get('top_average', {}).get('union', 0)}"
            ]
        }
        
        # rudy map
        info["rudy-horizontal" ] = {
            "path" : csv2png(json_map.get("rudy", {}).get("horizontal", "")),
            "info" : [
                f"max utilization : {json_util.get('rudy', {}).get('max', {}).get('horizontal', 0)}",
                f"top average : {json_util.get('rudy', {}).get('top_average', {}).get('horizontal', 0)}"
            ]
        }
        
        info["rudy-vertical" ] = {
            "path" : csv2png(json_map.get("rudy", {}).get("vertical", "")),
            "info" : [
                f"max utilization : {json_util.get('rudy', {}).get('max', {}).get('vertical', 0)}",
                f"top average : {json_util.get('rudy', {}).get('top_average', {}).get('vertical', 0)}"
            ]
        }
        
        info["rudy-union" ] = {
            "path" : csv2png(json_map.get("rudy", {}).get("union", "")),
            "info" : [
                f"max utilization : {json_util.get('rudy', {}).get('max', {}).get('union', 0)}",
                f"top average : {json_util.get('rudy', {}).get('top_average', {}).get('union', 0)}"
            ]
        }
        
    
    return info


def build_maps_density(workspace: Workspace, 
                       step: WorkspaceStep) -> dict:     
    info = {}
    
    json_data = json_read(step.feature.get("map", ""))
    if len(json_data) > 0:
        json_density = json_data.get("Density", {})
        
        # cell
        info["cell density" ] = {
            "path" : csv2png(json_density.get("cell", {}).get("allcell_density", "")),
            "info" : []
        }
        
        info["macro density" ] = {
            "path" : csv2png(json_density.get("cell", {}).get("macro_density", "")),
            "info" : []
        }
        
        info["stdcell density" ] = {
            "path" : csv2png(json_density.get("cell", {}).get("stdcell_density", "")),
            "info" : []
        }
        
        info["net density" ] = {
            "path" : csv2png(json_density.get("net", {}).get("allnet_density", "")),
            "info" : []
        }
        
        info["global net density" ] = {
            "path" : csv2png(json_density.get("net", {}).get("global_net_density", "")),
            "info" : []
        }
        
        info["local net density" ] = {
            "path" : csv2png(json_density.get("net", {}).get("local_net_density", "")),
            "info" : []
        }
        
        info["pin density" ] = {
            "path" : csv2png(json_density.get("pin", {}).get("allcell_pin_density", "")),
            "info" : []
        }
    
    return info

def build_checklist(workspace: Workspace, 
                    step: WorkspaceStep) -> dict:          
    info = {
        "path" : step.checklist.get("path", "")
    }
    
    return info

def build_sta(workspace: Workspace, 
                    step: WorkspaceStep) -> dict:          
    top_module = workspace.design.top_module
    sta_data_dir = step.data.get(f"{StepEnum.STA.value}", "")
    if not sta_data_dir:
        sta_data_dir = os.path.join(step.directory, "data", "sta")

    sta_report = step.report.get("sta", {})
    info = {
        "timing": sta_report.get("timing", os.path.join(sta_data_dir, f"{top_module}.rpt")),
        "hold": sta_report.get("hold", os.path.join(sta_data_dir, f"{top_module}_hold.skew")),
        "setup": sta_report.get("setup", os.path.join(sta_data_dir, f"{top_module}_setup.skew")),
        "cap": sta_report.get("cap", os.path.join(sta_data_dir, f"{top_module}.cap")),
        "fanout": sta_report.get("fanout", os.path.join(sta_data_dir, f"{top_module}.fanout")),
        "trans": sta_report.get("trans", os.path.join(sta_data_dir, f"{top_module}.trans")),
    }

    return info