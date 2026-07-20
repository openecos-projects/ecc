from __future__ import annotations

from chipcompiler.data import Workspace, WorkspaceStep
from chipcompiler.utility import dict_to_str
from chipcompiler.utility.path import stringify_paths


def get_step_info(workspace: Workspace, step: WorkspaceStep, id: str) -> dict:
    step_info = {}

    match id:
        case "input":
            step_info = stringify_paths(step.input)
        case "output":
            step_info = stringify_paths(step.output)
        case "subflow":
            step_info = build_subflow(step)
        case "checklist":
            step_info = build_checklist(step)
        case "config" | "script":
            step_info = build_config(step)

    workspace.logger.log_section(f"[sizer] get step info, id = {id}")
    workspace.logger.info(f"{dict_to_str(step_info)}")

    return step_info


def build_subflow(step: WorkspaceStep) -> dict:
    return {"path": stringify_paths(step.subflow.get("path", ""))}


def build_checklist(step: WorkspaceStep) -> dict:
    return {"path": stringify_paths(step.checklist.get("path", ""))}


def build_config(step: WorkspaceStep) -> dict:
    return {
        "sizer_env": stringify_paths(step.script.sizer_env or ""),
        "sizer_cmd": stringify_paths(step.script.sizer_cmd or ""),
    }
