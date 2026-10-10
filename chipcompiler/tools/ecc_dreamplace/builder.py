#!/usr/bin/env python

import math
import os
from copy import deepcopy
from pathlib import Path

from chipcompiler.data import (
    EccStep,
    StepEnum,
    Workspace,
    WorkspaceStep,
    build_workspace_config_paths,
)
from chipcompiler.data.config_params.dreamplace_sizing import DEFAULT_DIFF_SIZING_COEFFICIENTS
from chipcompiler.tools.ecc import builder as ecc_builder
from chipcompiler.tools.ecc_dreamplace.parameter_overrides import (
    apply_direct_config_overrides,
)
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
        if str(parameter_path).endswith(".toml"):
            from chipcompiler.data.parameter import load_parameter

            return load_parameter(Path(parameter_path)).data
        return json_read(parameter_path)

    return workspace.parameters.data


def _set_step_fields(params: dict, step: WorkspaceStep) -> dict:
    params["def_input"] = str(step.input.def_ or "")
    params["verilog_input"] = str(step.input.verilog or "")
    params["result_dir"] = str(step.data.workdir_for(step.name))
    return params


def step_config_path(workspace: Workspace, step: WorkspaceStep) -> Path:
    if step.name == StepEnum.DIFF_SIZING.value:
        return Path(step.data.workdir_for(step.name)) / "dreamplace_diff_sizing.json"
    return Path(workspace.config["dreamplace"])


def _apply_diff_sizing_defaults(params: dict) -> dict:
    """Apply the standalone DreamPlace S50/RRR3 profile to a diff-sizing step."""
    result = deepcopy(params)
    continuous_steps = result.get("diff_sizing_continuous_steps", 0)
    if (
        isinstance(continuous_steps, bool)
        or not isinstance(continuous_steps, int)
        or not 0 <= continuous_steps <= 1000
    ):
        raise ValueError("diff_sizing_continuous_steps must be an integer in [0, 1000]")
    policy = result.get("diff_sizing_coefficients", {})
    if not isinstance(policy, dict) or set(policy) - DEFAULT_DIFF_SIZING_COEFFICIENTS.keys():
        raise ValueError("diff_sizing_coefficients must be an object with wns, tns, cap, slew")
    coefficients = DEFAULT_DIFF_SIZING_COEFFICIENTS | policy
    for name, value in coefficients.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(f"diff_sizing_coefficients.{name} must be finite and nonnegative")
    result["diff_sizing_coefficients"] = coefficients
    result.update(
        flow_kind="sizing",
        place_io_engine="ecc",
        timing_rc_mode="gr",
        placement_sizing_mode="size_only",
        sizing_parameterization="real_size",
        real_size_execution_mode="warmup_to_discrete",
        real_size_warmup_steps=continuous_steps,
        continuous_size_dynamics_mode="none",
        target_density=0.4,
        cell_padding_x=0,
        auto_adjust_bins=0,
        num_bins_x=512,
        num_bins_y=512,
        route_num_bins_x=512,
        route_num_bins_y=512,
        timing_opt_enabled=0,
        timing_opt_flag=0,
        timing_eval_flag=1,
        routability_opt_flag=0,
        l_shape_routability_flag=0,
        adjust_gpugr_area_flag=0,
        gpugr_final_eval_flag=0,
        enable_net_weighting=0,
        pin2pin_net_weighting=0,
        buffering_continuous_relaxed_optimization=False,
        buffering_segment_count_tns_gradient=False,
        buffering_segment_strategy="continuous",
        buffering_candidate_strategy="continuous",
        enable_relaxed_buffer_timing=False,
        joint_segment_virtual_density_enabled=0,
        gpu=0,
        gpugr_backend="cpu_pr_maze",
        gr_sizing_rrr_iters=3,
        enable_fillers=0,
        random_center_init_flag=0,
        legalize_flag=1,
        detailed_place_flag=0,
        detailed_place_engine="",
        diff_sizing_continuous_steps=continuous_steps,
        timing_wns_coeff=coefficients["wns"],
        timing_tns_coeff=coefficients["tns"],
        timing_cap_weight=coefficients["cap"],
        timing_slew_weight=coefficients["slew"],
        timing_grad_balance_weight=1.0,
        timing_grad_balance_target_ratio=0.0,
    )
    if continuous_steps == 0:
        result.update(
            sizing_parameterization="logits",
            real_size_execution_mode="continuous_only",
            real_size_warmup_steps=0,
            continuous_size_dynamics_mode="discrete_gradient_topk",
        )
    stages = list(result.get("global_place_stages") or [{}])
    first_stage = dict(stages[0]) if isinstance(stages[0], dict) else {}
    first_stage.update(num_bins_x=512, num_bins_y=512, iteration=50, optimizer="adam")
    result["global_place_stages"] = [first_stage]
    return result


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
    parameter_data = _current_parameter_data(workspace)
    params = apply_parameter_overrides(params, parameter_data)
    params = apply_direct_config_overrides(params, parameter_data)
    if step.name == StepEnum.DIFF_SIZING.value:
        params = _apply_diff_sizing_defaults(params)

    from dreamplace.flows.flow_config import resolve_flow_config

    dreamplace_overrides = parameter_data.get("dreamplace")
    explicit_keys = set(dreamplace_overrides) if isinstance(dreamplace_overrides, dict) else set()
    explicit_keys.update(apply_direct_config_overrides({}, parameter_data))
    params = resolve_flow_config(params, explicit_keys=explicit_keys)
    # Canonical profiles own defaults; explicit workspace values own the final
    # effective config and therefore must be replayed after profile expansion.
    params = apply_parameter_overrides(params, parameter_data)
    params = apply_direct_config_overrides(params, parameter_data)
    if step.name == StepEnum.DIFF_SIZING.value:
        # Workspace-level placement values (density, padding and routability)
        # are intentionally not shared with the standalone sizing lane.
        params = _apply_diff_sizing_defaults(params)
    params = _set_step_fields(params, step)

    config_path = step_config_path(workspace, step)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    json_write(config_path, params)
