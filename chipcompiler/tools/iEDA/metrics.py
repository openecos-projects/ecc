#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from chipcompiler.data import (
    Workspace, 
    WorkspaceStep, 
    StepMetrics, 
    save_metrics,
    StepEnum
)
from chipcompiler.utility import json_read, plot_metrics


def build_step_metrics(workspace: Workspace, 
                       step: WorkspaceStep) -> StepMetrics:
    """
    Build and return a StepMetrics instance for the given workspace step.
    """
    
    # step matrics
    match(step.name):
        case StepEnum.FLOORPLAN.value:
            return build_metrics_floorplan(workspace, step)
        case StepEnum.NETLIST_OPT.value:
            return build_metrics_net_opt(workspace, step)
        case StepEnum.PLACEMENT.value:
            return build_metrics_placement(workspace, step)
        case StepEnum.CTS.value:
            return build_metrics_cts(workspace, step)
        case StepEnum.TIMING_OPT_DRV.value:
            return build_metrics_timing_opt_drv(workspace, step)
        case StepEnum.TIMING_OPT_HOLD.value:
            return build_metrics_timing_opt_hold(workspace, step)
        case StepEnum.LEGALIZATION.value:
            return build_metrics_legalization(workspace, step)
        case StepEnum.ROUTING.value:
            return build_metrics_routing(workspace, step)
        case StepEnum.DRC.value:
            return build_metrics_drc(workspace, step)
        case StepEnum.FILLER.value:
            return build_metrics_filler(workspace, step)
    
    return None

def build_metrics_db(workspace: Workspace, 
                    step: WorkspaceStep) -> dict:
    # db summary matrics
    metrics = {}
    data = json_read(step.feature.get('db', ""))
    if len(data) > 0:
        metrics["Die area [μm^2]"] = f"{round(data.get('Design Layout', {}).get('die_area', 0.0), 3)}"
        metrics["Die width [um]"] = f"{data.get('Design Layout', {}).get('die_bounding_width', 0.0)}"
        metrics["Die height [um]"] = f"{data.get('Design Layout', {}).get('die_bounding_height', 0.0)}"
        metrics["Die util"] = f"{round(data.get('Design Layout', {}).get('die_usage', 0.0), 2)}"
        metrics["Core util"] = f"{round(data.get('Design Layout', {}).get('core_usage', 0.0), 2)}"
        metrics["Total instances"] = data.get('Design Statis', {}).get('num_instances', 0)
        metrics["Total io pins"] = data.get('Design Statis', {}).get('num_iopins', 0)
        metrics["Total nets"] = data.get('Design Statis', {}).get('num_nets', 0)

    return metrics


def build_metrics_net_opt(workspace: Workspace, 
                           step: WorkspaceStep) -> StepMetrics:
    """
    Build and return net operation metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']    
    
    metrics = {}
    metrics['Design'] = workspace.design.name
    metrics['Step'] = step.name
    metrics['Tool'] = step.tool
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    json_path = step.feature.get('step', "")
    data = json_read(json_path)
    if len(data) > 0:
        metrics["Max fanout"] = workspace.parameters.data.get("Max fanout", 0)
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = json_path.replace(".csv", ".png")
    plot_metrics(metrics=step_metrics.data, output_path=image_path)
    
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
    metrics['Design'] = workspace.design.name
    metrics['Step'] = step.name
    metrics['Tool'] = step.tool
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    data = json_read(step.feature.get('step', ""))
    if len(data) > 0:
        # Add filler specific metrics here
        pass
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = f"{step.analysis.get('dir', '')}/statis.png"
    plot_metrics(metrics=step_metrics.data, output_path=image_path)
    
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
    metrics['Design'] = workspace.design.name
    metrics['Step'] = step.name
    metrics['Tool'] = step.tool
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    data = json_read(step.feature.get('step', ""))
    if len(data) > 0:
        # Add DRC specific metrics here
        pass
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = f"{step.analysis.get('dir', '')}/statis.png"
    plot_metrics(metrics=step_metrics.data, output_path=image_path)
    
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
    metrics['Design'] = workspace.design.name
    metrics['Step'] = step.name
    metrics['Tool'] = step.tool
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    data = json_read(step.feature.get('step', ""))
    if len(data) > 0:
        # Add routing specific metrics here
        pass
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = f"{step.analysis.get('dir', '')}/statis.png"
    plot_metrics(metrics=step_metrics.data, output_path=image_path)
    
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
    metrics['Design'] = workspace.design.name
    metrics['Step'] = step.name
    metrics['Tool'] = step.tool
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    data = json_read(step.feature.get('step', ""))
    if len(data) > 0:
        # Add legalization specific metrics here
        pass
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = f"{step.analysis.get('dir', '')}/statis.png"
    plot_metrics(metrics=step_metrics.data, output_path=image_path)
    
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
    metrics['Design'] = workspace.design.name
    metrics['Step'] = step.name
    metrics['Tool'] = step.tool
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    data = json_read(step.feature.get('step', ""))
    if len(data) > 0:
        # Add timing optimization (hold) specific metrics here
        pass
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = f"{step.analysis.get('dir', '')}/statis.png"
    plot_metrics(metrics=step_metrics.data, output_path=image_path)
    
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
    metrics['Design'] = workspace.design.name
    metrics['Step'] = step.name
    metrics['Tool'] = step.tool
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    data = json_read(step.feature.get('step', ""))
    if len(data) > 0:
        # Add timing optimization (driver) specific metrics here
        pass
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = f"{step.analysis.get('dir', '')}/statis.png"
    plot_metrics(metrics=step_metrics.data, output_path=image_path)
    
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
    metrics['Design'] = workspace.design.name
    metrics['Step'] = step.name
    metrics['Tool'] = step.tool
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    data = json_read(step.feature.get('step', ""))
    if len(data) > 0:
        # Add CTS specific metrics here
        pass
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = f"{step.analysis.get('dir', '')}/statis.png"
    plot_metrics(metrics=step_metrics.data, output_path=image_path)
    
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
    metrics['Design'] = workspace.design.name
    metrics['Step'] = step.name
    metrics['Tool'] = step.tool
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    data = json_read(step.feature.get('step', ""))
    if len(data) > 0:
        # Add placement specific metrics here
        pass
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = f"{step.analysis.get('dir', '')}/statis.png"
    plot_metrics(metrics=step_metrics.data, output_path=image_path)
    
    report = f"{step.name} step metrics:\n"
    
    step_metrics.report.append((image_path, report))
      
    if save_metrics(step_metrics):
        return step_metrics
    else:
        return None 


def build_metrics_floorplan(workspace: Workspace, 
                           step: WorkspaceStep) -> StepMetrics:
    """
    Build and return floorplan metrics dictionary.
    """
    step_metrics = StepMetrics()
    step_metrics.path = step.analysis['metrics']    
    
    metrics = {}
    metrics['Design'] = workspace.design.name
    metrics['Step'] = step.name
    metrics['Tool'] = step.tool
    
    # db summary matrics
    metrics.update(build_metrics_db(workspace, step))
    
    # step matrics
    data = json_read(step.feature.get('step', ""))
    if len(data) > 0:
        # Add floorplan specific metrics here
        pass
    
    step_metrics.data = metrics
    
    # generate report image and dscription
    image_path = f"{step.analysis.get('dir', '')}/statis.png"
    plot_metrics(metrics=step_metrics.data, output_path=image_path)
    
    report = f"{step.name} step metrics:\n"
    
    step_metrics.report.append((image_path, report))
      
    if save_metrics(step_metrics):
        return step_metrics
    else:
        return None 