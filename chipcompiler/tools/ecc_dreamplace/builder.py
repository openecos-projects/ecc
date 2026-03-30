#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from __future__ import annotations

import shutil
from pathlib import Path

from chipcompiler.data import Workspace, WorkspaceStep
from chipcompiler.tools.ecc import builder as ecc_builder
from chipcompiler.utility import json_read, json_write

def build_step(
    workspace: Workspace,
    step_name: str,
    input_def: str,
    input_verilog: str,
    output_def: str | None = None,
    output_verilog: str | None = None,
    output_gds: str | None = None,
) -> WorkspaceStep:
    step = ecc_builder.build_step(
        workspace=workspace,
        step_name=step_name,
        input_def=input_def,
        input_verilog=input_verilog,
        output_def=output_def,
        output_verilog=output_verilog,
        output_gds=output_gds,
        tool = "dreamplace"
    )
    
    step.config["dreamplace"] = f"{step.config['dir']}/dreamplace.json"
    
    return step

def build_step_space(step: WorkspaceStep) -> None:
    ecc_builder.build_step_space(step)

def build_step_config(workspace: Workspace, step: WorkspaceStep) -> None:
    # build ecc config
    ecc_builder.build_step_config(workspace, step)
    
    # build dreamplace config
    param_src = Path(__file__).resolve().parent / "configs" / "dreamplace.json"
    shutil.copy2(param_src, step.config["dreamplace"])

    params = json_read(step.config["dreamplace"])

    params["lef_input"] = [workspace.pdk.tech, *workspace.pdk.lefs]
    params["def_input"] = step.input.get("def", "")
    params["verilog_input"] = step.input.get("verilog", "")
    params["result_dir"] = step.data.get(step.name, step.data["dir"])
    params["base_design_name"] = workspace.design.name
    workspace_target_density = workspace.parameters.data.get(
        "target_density", workspace.parameters.data.get("Target density", 0.3)
    )
    workspace_stop_overflow = workspace.parameters.data.get(
        "stop_overflow", workspace.parameters.data.get("Target overflow", 0.1)
    )
    params["target_density"] = params.get("target_density", workspace_target_density)
    params["stop_overflow"] = params.get("stop_overflow", workspace_stop_overflow)
    params["timing_opt_flag"] = 0
    params["timing_eval_flag"] = 0
    params["with_sta"] = 0
    params["differentiable_timing_obj"] = 0

    json_write(step.config["dreamplace"], params)
