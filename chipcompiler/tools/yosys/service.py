#!/usr/bin/env python
from chipcompiler.data import Workspace, YosysStep
from chipcompiler.utility import dict_to_str
from chipcompiler.utility.path import stringify_paths


def get_step_info(workspace: Workspace, step: YosysStep, id: str) -> dict:
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
        case "config":
            step_info = build_config(workspace=workspace, step=step)

    workspace.logger.log_section(f"[yosys] get step info, id = {id}")
    workspace.logger.info(f"{dict_to_str(step_info)}")

    return step_info


def build_views(workspace: Workspace, step: YosysStep) -> dict:
    info = {
        "image": stringify_paths(step.output.image or ""),
        "metrics": stringify_paths(step.analysis.metrics or ""),
        "information": {},
    }

    return info


def build_layout(workspace: Workspace, step: YosysStep) -> dict:
    info = {
        "image": stringify_paths(step.output.image or ""),
    }

    return info


def build_metrics(workspace: Workspace, step: YosysStep) -> dict:
    info = {"metrics": stringify_paths(step.analysis.metrics or "")}

    return info


def build_subflow(workspace: Workspace, step: YosysStep) -> dict:
    info = {"path": stringify_paths(step.subflow.path or "")}

    return info


def build_config(workspace: Workspace, step: YosysStep) -> dict:
    return {"path": stringify_paths(workspace.config.get("flow", ""))}


def build_analysis(workspace: Workspace, step: YosysStep) -> dict:
    info = {
        "metrics": stringify_paths(step.analysis.metrics or ""),
        "data summary": stringify_paths(step.feature.stat or ""),
        "step report": stringify_paths(step.report.check or ""),
    }

    return info


def build_maps(workspace: Workspace, step: YosysStep) -> dict:
    info = {}

    return info


def build_checklist(workspace: Workspace, step: YosysStep) -> dict:
    info = {"path": stringify_paths(step.checklist.path or "")}

    return info
