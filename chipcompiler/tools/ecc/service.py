#!/usr/bin/env python
from chipcompiler.data import StepEnum, Workspace, WorkspaceStep
from chipcompiler.tools.ecc.metrics import build_step_metrics
from chipcompiler.utility import json_read


def get_step_info(workspace: Workspace, step: WorkspaceStep, id: str) -> dict:
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

    return step_info


def build_views(workspace: Workspace, step: WorkspaceStep) -> dict:
    metrics = build_step_metrics(workspace=workspace, step=step)

    info = {"image": step.output.get("image", ""), "metrics": metrics.path, "information": {}}

    return info


def build_metrics(workspace: Workspace, step: WorkspaceStep) -> dict:
    metrics = build_step_metrics(workspace=workspace, step=step)
    info = {"metrics": metrics.path}

    return info


def build_layout(workspace: Workspace, step: WorkspaceStep) -> dict:
    info = {"image": step.output.get("image", "")}

    return info


def build_subflow(workspace: Workspace, step: WorkspaceStep) -> dict:
    info = {"path": step.subflow.get("path", "")}

    return info


def build_analysis(workspace: Workspace, step: WorkspaceStep) -> dict:
    info = {
        "metrics": step.analysis.get("metrics", ""),
        "statis": step.analysis.get("statis_csv", ""),
        "data summary": step.feature.get("db", ""),
        "step feature": step.feature.get("step", ""),
        "step report": step.report.get("db", ""),
    }

    return info


def build_maps(workspace: Workspace, step: WorkspaceStep) -> dict:
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


def build_maps_congestion(workspace: Workspace, step: WorkspaceStep) -> dict:
    info = {}

    json_data = json_read(step.feature.get("map", ""))
    if len(json_data) > 0:
        json_cong = json_data.get("Congestion", {})
        json_map = json_cong.get("map", {})
        json_util = json_cong.get("utilization", {})

        lutrudy_util = json_util.get("lutrudy", {})
        rudy_util = json_util.get("rudy", {})

        # egr maps
        info["egr-horizontal"] = {
            "path": json_map.get("egr", {}).get("horizontal", ""),
            "info": [""],
        }

        info["egr-vertical"] = {"path": json_map.get("egr", {}).get("vertical", ""), "info": [""]}

        info["egr-union"] = {"path": json_map.get("egr", {}).get("union", ""), "info": [""]}

        # lut rudy map
        info["lutrudy-horizontal"] = {
            "path": json_map.get("lutrudy", {}).get("horizontal", ""),
            "info": [
                f"max utilization : {lutrudy_util.get('max', {}).get('horizontal', 0)}",
                f"top average : {lutrudy_util.get('top_average', {}).get('horizontal', 0)}",
            ],
        }

        info["lutrudy-vertical"] = {
            "path": json_map.get("lutrudy", {}).get("vertical", ""),
            "info": [
                f"max utilization : {lutrudy_util.get('max', {}).get('vertical', 0)}",
                f"top average : {lutrudy_util.get('top_average', {}).get('vertical', 0)}",
            ],
        }

        info["lutrudy-union"] = {
            "path": json_map.get("lutrudy", {}).get("union", ""),
            "info": [
                f"max utilization : {lutrudy_util.get('max', {}).get('union', 0)}",
                f"top average : {lutrudy_util.get('top_average', {}).get('union', 0)}",
            ],
        }

        # rudy map
        info["rudy-horizontal"] = {
            "path": json_map.get("rudy", {}).get("horizontal", ""),
            "info": [
                f"max utilization : {rudy_util.get('max', {}).get('horizontal', 0)}",
                f"top average : {rudy_util.get('top_average', {}).get('horizontal', 0)}",
            ],
        }

        info["rudy-vertical"] = {
            "path": json_map.get("rudy", {}).get("vertical", ""),
            "info": [
                f"max utilization : {rudy_util.get('max', {}).get('vertical', 0)}",
                f"top average : {rudy_util.get('top_average', {}).get('vertical', 0)}",
            ],
        }

        info["rudy-union"] = {
            "path": json_map.get("rudy", {}).get("union", ""),
            "info": [
                f"max utilization : {rudy_util.get('max', {}).get('union', 0)}",
                f"top average : {rudy_util.get('top_average', {}).get('union', 0)}",
            ],
        }

    return info


def build_maps_density(workspace: Workspace, step: WorkspaceStep) -> dict:
    info = {}

    json_data = json_read(step.feature.get("map", ""))
    if len(json_data) > 0:
        json_density = json_data.get("Density", {})

        # cell
        info["cell density"] = {
            "path": json_density.get("cell", {}).get("allcell_density", ""),
            "info": [],
        }

        info["macro density"] = {
            "path": json_density.get("cell", {}).get("macro_density", ""),
            "info": [],
        }

        info["stdcell density"] = {
            "path": json_density.get("cell", {}).get("stdcell_density", ""),
            "info": [],
        }

        info["net density"] = {
            "path": json_density.get("net", {}).get("allnet_density", ""),
            "info": [],
        }

        info["global net density"] = {
            "path": json_density.get("net", {}).get("global_net_density", ""),
            "info": [],
        }

        info["local net density"] = {
            "path": json_density.get("net", {}).get("local_net_density", ""),
            "info": [],
        }

        info["pin density"] = {
            "path": json_density.get("pin", {}).get("allcell_pin_density", ""),
            "info": [],
        }

    return info


def build_checklist(workspace: Workspace, step: WorkspaceStep) -> dict:
    info = {"path": step.checklist.get("path", "")}

    return info
