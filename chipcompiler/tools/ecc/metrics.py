#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from chipcompiler.data import (
    Workspace, 
    WorkspaceStep, 
    StepMetrics, 
    save_metrics,
    StepEnum,
    StateEnum
)
from chipcompiler.utility import json_read

from chipcompiler.tools.ecc.subflow import EccSubFlow, EccSubFlowEnum


def build_step_metrics(workspace: Workspace, 
                       step: WorkspaceStep,
                       subflow: EccSubFlow = None) -> StepMetrics:
    """
    Build and return a StepMetrics instance for the given workspace step.
    """
    # update sub flow metrics state
    sub_flow = subflow if subflow is not None else EccSubFlow(workspace=workspace, workspace_step=step)
    
    # step matrics
    metrics = None
    match(step.name):
        case StepEnum.FLOORPLAN.value:
            metrics = build_metrics_floorplan(workspace, step)
        case StepEnum.NETLIST_OPT.value:
            metrics = build_metrics_net_opt(workspace, step)
        case StepEnum.PLACEMENT.value:
            metrics = build_metrics_placement(workspace, step)
        case StepEnum.CTS.value:
            metrics = build_metrics_cts(workspace, step)
        case StepEnum.TIMING_OPT_DRV.value:
            metrics = build_metrics_timing_opt_drv(workspace, step)
        case StepEnum.TIMING_OPT_HOLD.value:
            metrics = build_metrics_timing_opt_hold(workspace, step)
        case StepEnum.LEGALIZATION.value:
            metrics = build_metrics_legalization(workspace, step)
        case StepEnum.ROUTING.value:
            metrics = build_metrics_routing(workspace, step)
        case StepEnum.DRC.value:
            metrics = build_metrics_drc(workspace, step)
        case StepEnum.FILLER.value:
            metrics = build_metrics_filler(workspace, step)
    
    info = {}        
    data = json_read(step.feature.get("db", ""))
    if data is not None:
        instance_num = data.get("Design Statis", {}).get("num_instances", 0) 
        info["instance"] = instance_num

        if metrics.data.get("Frequency [MHz]", 0) > 0:
            info["frequency"] = metrics.data.get("Frequency [MHz]", 0)   
    
    sub_flow.update_step(step_name=EccSubFlowEnum.analysis.value,
                         state=StateEnum.Invalid if metrics is None else StateEnum.Success,
                         info=info)
    
    return metrics


def build_metrics_timing(workspace: Workspace, 
                         step: WorkspaceStep) -> dict:
    metrics = {}
    
    data = json_read(step.feature.get('timing', ""))
    max_WNS = None
    if len(data) > 0:
        for slack_item in data.get('slack', []):
            type = slack_item.get("delay_type", "")
            metrics[f"{type}_TNS"] = slack_item.get("TNS", 0)
            metrics[f"{type}_WNS"] = slack_item.get("WNS", 0)
            
            if type == "max":
                max_WNS = float(slack_item.get("WNS", 0))
            
    # frequency
    frequency = workspace.parameters.data.get("Frequency max [MHz]", 0)
    if frequency > 0 and max_WNS is not None:
        clk_period = 1000.0 / frequency
        
        real_frequency = 1000.0 / (clk_period - max_WNS) if max_WNS is not None else 0
        metrics["Frequency [MHz]"] = round(real_frequency, 2)

    return metrics

def build_metrics_db(workspace: Workspace, 
                    step: WorkspaceStep) -> dict:
    # db summary matrics
    metrics = {}
    
    metrics['Tool'] = step.tool
    
    data = json_read(step.feature.get('db', ""))
    if len(data) > 0:
        metrics["Die area [μm^2]"] = f"{round(data.get('Design Layout', {}).get('die_area', 0.0), 3)}"
        metrics["Die width [um]"] = f"{data.get('Design Layout', {}).get('die_bounding_width', 0.0)}"
        metrics["Die height [um]"] = f"{data.get('Design Layout', {}).get('die_bounding_height', 0.0)}"
        metrics["Die util"] = f"{round(data.get('Design Layout', {}).get('die_usage', 0.0), 2)}"
        metrics["Core util"] = f"{round(data.get('Design Layout', {}).get('core_usage', 0.0), 2)}"
        metrics["Total io pins"] = data.get('Design Statis', {}).get('num_iopins', 0)
        metrics["Total instances"] = data.get('Design Statis', {}).get('num_instances', 0)
        metrics["Total nets"] = data.get('Design Statis', {}).get('num_nets', 0)
        
    metrics.update(build_metrics_timing(workspace=workspace, step=step))

    return metrics

def build_metrics_floorplan(workspace: Workspace, 
                            step: WorkspaceStep) -> StepMetrics:
    """
    Build and return floorplan metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']    
    
    metrics = {}
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    json_path = step.feature.get('step', "")
    data = json_read(json_path)
    if len(data) > 0:
        # Add floorplan specific metrics here
        pass
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = json_path.replace(".json", ".png")
    report = f"{step.name} step metrics:\n"
    
    step_metrics.report.append((image_path, report))
      
    if save_metrics(step_metrics):
        return step_metrics
    else:
        return None 

def build_metrics_net_opt(workspace: Workspace, 
                          step: WorkspaceStep) -> StepMetrics:
    """
    Build and return net operation metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']    
    
    metrics = {}
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # # step matrics
    json_path = step.feature.get('step', "")

    metrics["Max fanout"] = workspace.parameters.data.get("Max fanout", 0)
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = json_path.replace(".json", ".png")
    report = f"{step.name} step metrics:\n"
    
    step_metrics.report.append((image_path, report))
      
    if save_metrics(step_metrics):
        return step_metrics
    else:
        return None 


def build_metrics_filler(workspace: Workspace, 
                         step: WorkspaceStep) -> StepMetrics:
    """
    Build and return filler metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']    
    
    metrics = {}
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    json_path = step.feature.get('step', "")
    data = json_read(json_path)
    if len(data) > 0:
        # Add filler specific metrics here
        pass
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = json_path.replace(".json", ".png") 
    report = f"{step.name} step metrics:\n"
    
    step_metrics.report.append((image_path, report))
      
    if save_metrics(step_metrics):
        return step_metrics
    else:
        return None 


def build_metrics_drc(workspace: Workspace, 
                      step: WorkspaceStep) -> StepMetrics:
    """
    Build and return DRC metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']    
    
    metrics = {}

    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    json_path = step.feature.get('step', "")
    data = json_read(json_path)
    if len(data) > 0:
        metrics["drc_num"] = data.get("drc", {}).get("number", 0)
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = json_path.replace(".json", ".png")
    report = f"{step.name} step metrics:\n"
    
    step_metrics.report.append((image_path, report))
      
    if save_metrics(step_metrics):
        return step_metrics
    else:
        return None 


def build_metrics_routing(workspace: Workspace, 
                          step: WorkspaceStep) -> StepMetrics:
    """
    Build and return routing metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']    
    
    metrics = {}

    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    json_path = step.feature.get('db', "")
    data = json_read(json_path)
    if len(data) > 0:
        metrics["wire_len"] = data.get("Nets", {}).get("wire_len", 0)
        metrics["num_via"] = data.get("Nets", {}).get("num_via", 0)
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = json_path.replace(".json", ".png")
    report = f"{step.name} step metrics:\n"
    
    step_metrics.report.append((image_path, report))
      
    if save_metrics(step_metrics):
        return step_metrics
    else:
        return None 


def build_metrics_legalization(workspace: Workspace, 
                               step: WorkspaceStep) -> StepMetrics:
    """
    Build and return legalization metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']    
    
    metrics = {}
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    json_path = step.feature.get('step', "")
    data = json_read(json_path)
    if len(data) > 0:
        metrics["total_movement"] = data.get("legalization", {}).get("total_movement", 0)
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = json_path.replace(".json", ".png")
    report = f"{step.name} step metrics:\n"
    
    step_metrics.report.append((image_path, report))
      
    if save_metrics(step_metrics):
        return step_metrics
    else:
        return None 


def build_metrics_timing_opt_hold(workspace: Workspace, 
                                  step: WorkspaceStep) -> StepMetrics:
    """
    Build and return timing optimization (hold) metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']    
    
    metrics = {}

    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    json_path = step.feature.get('step', "")
    # data = json_read(json_path)
    # if len(data) > 0:
    #     for clk_item in data.get("optHold", {}).get("clocks_timing", []):
    #         metrics["suggest_freq"] = clk_item.get("opt_suggest_freq", 0)
    #         metrics["hold_wns"] = clk_item.get("opt_wns", 0)
    #         metrics["hold_tns"] = clk_item.get("opt_tns", 0)
            
    #         break
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = json_path.replace(".json", ".png")
    report = f"{step.name} step metrics:\n"
    
    step_metrics.report.append((image_path, report))
      
    if save_metrics(step_metrics):
        return step_metrics
    else:
        return None 


def build_metrics_timing_opt_drv(workspace: Workspace, 
                                 step: WorkspaceStep) -> StepMetrics:
    """
    Build and return timing optimization (driver) metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']    
    
    metrics = {}
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    json_path = step.feature.get('step', "")
    # data = json_read(json_path)
    # if len(data) > 0:
    #     for clk_item in data.get("optDrv", {}).get("clocks_timing", []):
    #         metrics["suggest_freq"] = clk_item.get("opt_suggest_freq", 0)
    #         metrics["wns"] = clk_item.get("opt_wns", 0)
    #         metrics["tns"] = clk_item.get("opt_tns", 0)
            
    #         break
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = json_path.replace(".json", ".png")
    report = f"{step.name} step metrics:\n"
    
    step_metrics.report.append((image_path, report))
      
    if save_metrics(step_metrics):
        return step_metrics
    else:
        return None 

def build_metrics_cts(workspace: Workspace, 
                      step: WorkspaceStep) -> StepMetrics:
    """
    Build and return CTS metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']    
    
    metrics = {}
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    json_path = step.feature.get('step', "")
    data = json_read(json_path)
    if len(data) > 0:
        metrics["buffer_num"] = data.get("CTS", {}).get("buffer_num", 0)
        metrics["buffer_area"] = data.get("CTS", {}).get("buffer_area", 0)
        metrics["clock_path_max_buffer"] = data.get("CTS", {}).get("clock_path_max_buffer", 0)
        metrics["clock_path_min_buffer"] = data.get("CTS", {}).get("clock_path_min_buffer", 0)
        metrics["total_clock_wirelength"] = data.get("CTS", {}).get("total_clock_wirelength", 0)
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = json_path.replace(".json", ".png")
    report = f"{step.name} step metrics:\n"
    
    step_metrics.report.append((image_path, report))
      
    if save_metrics(step_metrics):
        return step_metrics
    else:
        return None 


def build_metrics_placement(workspace: Workspace, 
                            step: WorkspaceStep) -> StepMetrics:
    """
    Build and return placement metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']    
    
    metrics = {}
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    json_path = step.feature.get('step', "")
    data = json_read(json_path)
    if len(data) > 0:
        metrics["overflow"] = data.get("place", {}).get("overflow", 0)
        metrics["overflow_number"] = data.get("place", {}).get("overflow_number", 0)
        metrics["bin_number"] = data.get("place", {}).get("bin_number", 0)
        metrics["GP HPWL"] = data.get("place", {}).get("gplace", {}).get("HPWL", 0) / 1000
        metrics["DP HPWL"] = data.get("place", {}).get("dplace", {}).get("STWL", 0) / 1000
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = json_path.replace(".json", ".png")
    report = f"{step.name} step metrics:\n"
    
    step_metrics.report.append((image_path, report))
      
    if save_metrics(step_metrics):
        return step_metrics
    else:
        return None 