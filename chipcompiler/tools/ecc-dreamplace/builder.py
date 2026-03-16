#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from __future__ import annotations

import shutil
from copy import deepcopy
from pathlib import Path

from chipcompiler.data import Workspace, WorkspaceStep
from chipcompiler.tools.ecc import builder as ecc_builder
from chipcompiler.utility import json_read, json_write


TOOL_NAME = "ecc-dreamplace"


def _replace_directory_prefix(value, old_prefix: str, new_prefix: str):
    if isinstance(value, str):
        return value.replace(old_prefix, new_prefix)
    if isinstance(value, dict):
        return {
            key: _replace_directory_prefix(item, old_prefix, new_prefix)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_directory_prefix(item, old_prefix, new_prefix) for item in value]
    if isinstance(value, tuple):
        return tuple(_replace_directory_prefix(item, old_prefix, new_prefix) for item in value)
    return deepcopy(value)


def _retarget_step_paths(step: WorkspaceStep, new_directory: str) -> WorkspaceStep:
    old_directory = step.directory
    step.directory = new_directory
    step.tool = TOOL_NAME

    for attr in (
        "config",
        "input",
        "output",
        "data",
        "feature",
        "report",
        "log",
        "script",
        "analysis",
        "subflow",
        "checklist",
        "result",
    ):
        value = getattr(step, attr)
        setattr(step, attr, _replace_directory_prefix(value, old_directory, new_directory))

    step.config["dreamplace"] = f"{step.config['dir']}/param.json"
    return step


def build_step(
    workspace: Workspace,
    step_name: str,
    input_def: str,
    input_verilog: str,
    output_def: str = None,
    output_verilog: str = None,
    output_gds: str = None,
) -> WorkspaceStep:
    step = ecc_builder.build_step(
        workspace=workspace,
        step_name=step_name,
        input_def=input_def,
        input_verilog=input_verilog,
        output_def=output_def,
        output_verilog=output_verilog,
        output_gds=output_gds,
    )
    new_directory = f"{workspace.directory}/{step_name}_{TOOL_NAME}"
    return _retarget_step_paths(step=step, new_directory=new_directory)


def build_step_space(step: WorkspaceStep) -> None:
    ecc_builder.build_step_space(step)


def _update_dreamplace_config(workspace: Workspace, step: WorkspaceStep) -> None:
    param_src = Path(__file__).resolve().parent / "configs" / "param.json"
    shutil.copy2(param_src, step.config["dreamplace"])

    params = json_read(step.config["dreamplace"])
    result_dir = Path(step.data.get(step.name, step.data["dir"])) / "dreamplace"
    result_dir.mkdir(parents=True, exist_ok=True)

    params["lef_input"] = [workspace.pdk.tech, *workspace.pdk.lefs]
    params["def_input"] = step.input.get("def", "")
    params["verilog_input"] = step.input.get("verilog", "")
    params["result_dir"] = str(result_dir)
    params["base_design_name"] = workspace.design.name
    params["target_density"] = workspace.parameters.data.get(
        "Target density", params.get("target_density", 0.3)
    )
    params["stop_overflow"] = workspace.parameters.data.get(
        "Target overflow", params.get("stop_overflow", 0.1)
    )
    params["timing_opt_flag"] = 0
    params["timing_eval_flag"] = 0
    params["with_sta"] = 0
    params["differentiable_timing_obj"] = 0

    json_write(step.config["dreamplace"], params)


def build_step_config(workspace: Workspace, step: WorkspaceStep) -> None:
    ecc_builder.build_step_config(workspace, step)
    _update_dreamplace_config(workspace, step)
