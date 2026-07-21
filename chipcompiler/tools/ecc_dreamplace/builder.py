#!/usr/bin/env python

from __future__ import annotations

import os
from pathlib import Path

from chipcompiler.data import EccStep, Workspace, WorkspaceStep, build_workspace_config_paths
from chipcompiler.tools.ecc import builder as ecc_builder
from chipcompiler.tools.ecc_dreamplace.parameter_overrides import (
    apply_parameter_overrides as _apply_parameter_overrides,
)
from chipcompiler.utility import json_read, json_write


def apply_parameter_overrides(
    base_params: dict,
    parameter_data: dict,
) -> dict:
    """Apply DreamPlace overrides onto a DreamPlace config dictionary.

    Kept as a compatibility entrypoint for external benchmark integrations.
    """
    return _apply_parameter_overrides(base_params, parameter_data)


def _current_parameter_data(workspace: Workspace) -> dict:
    parameter_path = workspace.parameters.path
    if parameter_path and os.path.exists(parameter_path):
        return json_read(parameter_path)

    return workspace.parameters.data


def _set_step_fields(params: dict, step: WorkspaceStep) -> dict:
    params["def_input"] = str(step.input.def_ or "")
    params["verilog_input"] = str(step.input.verilog or "")
    params["result_dir"] = str(step.data.workdir_for(step.name))
    return params


def build_step(
    workspace: Workspace,
    step_name: str,
    input_def: Path | None,
    input_verilog: Path | None,
    input_db: Path | str | None = None,
    output_def: Path | None = None,
    output_verilog: Path | None = None,
    output_gds: Path | None = None,
) -> EccStep:
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


def build_step_config(workspace: Workspace, step: EccStep) -> None:
    # build ecc config
    ecc_builder.build_step_config(workspace, step)

    from .checklist import DreamplaceChecklist

    DreamplaceChecklist(workspace=workspace, workspace_step=step)

    if not workspace.config:
        workspace.config = build_workspace_config_paths(workspace)

    params = json_read(workspace.config["dreamplace"])

    params = apply_parameter_overrides(params, _current_parameter_data(workspace))
    params = _set_step_fields(params, step)

    json_write(workspace.config["dreamplace"], params)
