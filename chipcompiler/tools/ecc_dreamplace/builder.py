#!/usr/bin/env python

from __future__ import annotations

from copy import deepcopy

from chipcompiler.data import Workspace, WorkspaceStep
from chipcompiler.data import build_workspace_config_paths
from chipcompiler.tools.ecc import builder as ecc_builder
from chipcompiler.utility import json_read, json_write


def apply_parameter_overrides(
    base_params: dict,
    parameter_data: dict,
) -> dict:
    """Apply direct DreamPlace overrides onto a DreamPlace config dictionary.

    Args:
        base_params: The generated DreamPlace config contents.
        parameter_data: The workspace ``home/parameters.json`` data.

    Returns:
        A copied config dictionary with ``DreamPlace`` values applied directly.
    """
    params = deepcopy(base_params)

    dreamplace_overrides = parameter_data.get("DreamPlace", {})
    if not isinstance(dreamplace_overrides, dict):
        return params

    for key, value in dreamplace_overrides.items():
        params[key] = deepcopy(value)

    return params


def build_step(
    workspace: Workspace,
    step_name: str,
    input_def: str,
    input_verilog: str,
    input_db: str | None = None,
    output_def: str | None = None,
    output_verilog: str | None = None,
    output_gds: str | None = None,
) -> WorkspaceStep:
    step = ecc_builder.build_step(
        workspace=workspace,
        step_name=step_name,
        input_def=input_def,
        input_verilog=input_verilog,
        input_db=input_db,
        output_def=output_def,
        output_verilog=output_verilog,
        output_gds=output_gds,
        tool="dreamplace",
    )

    return step


def build_step_space(step: WorkspaceStep) -> None:
    ecc_builder.build_step_space(step)


def build_step_config(workspace: Workspace, step: WorkspaceStep) -> None:
    # build ecc config
    ecc_builder.build_step_config(workspace, step)

    if not workspace.config:
        workspace.config = build_workspace_config_paths(workspace)

    params = json_read(workspace.config["dreamplace"])

    params["def_input"] = step.input.get("def", "")
    params["verilog_input"] = step.input.get("verilog", "")
    params["result_dir"] = step.data.get(step.name, step.data["dir"])

    json_write(workspace.config["dreamplace"], params)
