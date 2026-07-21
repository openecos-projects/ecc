from __future__ import annotations

from chipcompiler.data import EccStep, Workspace
from chipcompiler.utility import dict_to_str
from chipcompiler.utility.path import stringify_paths


def get_step_info(workspace: Workspace, step: EccStep, id: str) -> dict:
    step_info = {}

    match id:
        case "input":
            step_info = build_input(step)
        case "output":
            step_info = build_output(step)
        case "subflow":
            step_info = build_subflow(step)
        case "checklist":
            step_info = build_checklist(step)
        case "config" | "script":
            step_info = build_config(step)

    workspace.logger.log_section(f"[sizer] get step info, id = {id}")
    workspace.logger.info(f"{dict_to_str(step_info)}")

    return step_info


def build_input(step: EccStep) -> dict:
    return {
        "def": stringify_paths(step.input.def_),
        "verilog": stringify_paths(step.input.verilog),
        "db": stringify_paths(step.input.db),
    }


def build_output(step: EccStep) -> dict:
    output = step.output
    return {
        "dir": stringify_paths(output.dir),
        "def": stringify_paths(output.def_),
        "verilog": stringify_paths(output.verilog),
        "gds": stringify_paths(output.gds),
        "db": stringify_paths(output.db),
        "image": stringify_paths(output.image),
        "json": stringify_paths(output.json),
        "view_json": stringify_paths(output.view_json),
        "view_json_edits": stringify_paths(output.view_json_edits),
        "lef": stringify_paths(output.lef),
        "lib": stringify_paths(output.lib),
        "spef": stringify_paths(output.spef),
    }


def build_subflow(step: EccStep) -> dict:
    return {"path": stringify_paths(step.subflow.path or "")}


def build_checklist(step: EccStep) -> dict:
    return {"path": stringify_paths(step.checklist.path or "")}


def build_config(step: EccStep) -> dict:
    return {
        "sizer_env": stringify_paths(step.script.sizer_env or ""),
        "sizer_cmd": stringify_paths(step.script.sizer_cmd or ""),
    }
