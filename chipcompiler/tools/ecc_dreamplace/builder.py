#!/usr/bin/env python

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
from chipcompiler.tools.ecc import builder as ecc_builder
from chipcompiler.tools.ecc_dreamplace.parameter_overrides import (
    apply_direct_config_overrides,
)
from chipcompiler.tools.ecc_dreamplace.parameter_overrides import (
    apply_parameter_overrides as _apply_parameter_overrides,
)
from chipcompiler.utility import json_read, json_write

from .diff_opt import apply_diff_opt_defaults
from .diff_opt import prepare_drive_table as prepare_diff_opt_drive_table
from .timing_coefficients import resolve_timing_coefficients


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


def _apply_placement_buffering_profile(
    workspace: Workspace, step: EccStep, params: dict
) -> tuple[dict, set[str]]:
    """Expand the small placement buffering mode into internal lane settings."""

    if step.name != StepEnum.PLACEMENT.value or params.get("buffering_mode") != "candidate":
        return params, set()
    params = params | {
        "buffering_segment_strategy": "continuous",
        "buffering_candidate_strategy": "discrete_net_gradient",
        "buffering_candidate_drive_type_mode": "four_strength_table",
        # Placement S5B1 owns one Route-B scheduler round per window.  The
        # general buffering default is intentionally larger for standalone
        # buffering flows, so make the placement profile explicit here.
        "buffering_continuous_steps": 1,
        "buffering_fixed_buffer_master": "",
        "buffering_fixed_bsu_index": None,
    }
    params = prepare_diff_opt_drive_table(workspace, step, params)
    return params, {
        "buffering_segment_strategy",
        "buffering_candidate_strategy",
        "buffering_candidate_drive_type_mode",
        "buffering_candidate_drive_strength_table",
        "buffering_continuous_steps",
        "buffering_fixed_buffer_master",
        "buffering_fixed_bsu_index",
    }


def step_config_path(workspace: Workspace, step: WorkspaceStep) -> Path:
    if step.name == StepEnum.DIFF_OPT.value:
        return Path(step.data.workdir_for(step.name)) / "dreamplace_diff_opt.json"
    if step.name == StepEnum.DIFF_BUFFERING.value:
        return Path(step.data.workdir_for(step.name)) / "dreamplace_diff_buffering.json"
    if step.name == StepEnum.DIFF_SIZING.value:
        return Path(step.data.workdir_for(step.name)) / "dreamplace_diff_sizing.json"
    return Path(workspace.config["dreamplace"])


def _resolve_diff_sizing_rc_mode(result: dict, explicit_keys) -> str:
    explicit = set(explicit_keys or ())
    if "diff_sizing_timing_rc_mode" in explicit:
        mode = result.get("diff_sizing_timing_rc_mode", "gr")
    elif "timing_rc_mode" in explicit:
        mode = result.get("timing_rc_mode", "gr")
    elif "diff_sizing_timing_rc_mode" in result:
        mode = result.get("diff_sizing_timing_rc_mode")
    elif "timing_rc_mode" in result:
        mode = result.get("timing_rc_mode")
    else:
        mode = "gr"
    mode = str(mode or "gr")
    if mode not in {"placement", "gr"}:
        raise ValueError(
            "diff_sizing_timing_rc_mode must be one of: placement, gr"
        )
    return mode


def _apply_diff_sizing_defaults(params: dict, *, explicit_keys=None) -> dict:
    """Apply the standalone S50 profile with selectable placement/GR RC."""
    result = deepcopy(params)
    continuous_steps = result.get("diff_sizing_continuous_steps", 0)
    terminal_gr_sta_enabled = result.get("diff_sizing_terminal_gr_sta_enabled", 0)
    if terminal_gr_sta_enabled not in (0, 1, False, True):
        raise ValueError("diff_sizing_terminal_gr_sta_enabled must be 0 or 1")
    if (
        isinstance(continuous_steps, bool)
        or not isinstance(continuous_steps, int)
        or not 0 <= continuous_steps <= 1000
    ):
        raise ValueError("diff_sizing_continuous_steps must be an integer in [0, 1000]")
    action_mode = str(
        result.get("timing_action_gradient_mode", "lut_action") or "lut_action"
    )
    if action_mode not in {"off", "lut_action"}:
        raise ValueError(
            "timing_action_gradient_mode must be one of: off, lut_action"
        )
    score_objective = str(
        result.get("timing_action_score_objective", "loss") or "loss"
    )
    if score_objective not in {"loss", "tns", "wns"}:
        raise ValueError(
            "timing_action_score_objective must be one of: loss, tns, wns"
        )
    if action_mode == "lut_action" and continuous_steps != 0:
        raise ValueError(
            "lut_action standalone diff_sizing requires "
            "diff_sizing_continuous_steps=0"
        )
    from dreamplace.flows.diff_sizing_spec import parse_diff_sizing_flows

    flows = parse_diff_sizing_flows(
        result.get("diff_sizing_optimization_flows")
    )
    if flows is not None and action_mode != "lut_action":
        raise ValueError(
            "diff_sizing_optimization_flows requires "
            "timing_action_gradient_mode=lut_action"
        )
    if flows is not None:
        result["diff_sizing_optimization_flows"] = [
            spec.to_list() for spec in flows
        ]
    timing_rc_mode = _resolve_diff_sizing_rc_mode(result, explicit_keys)
    coefficients = resolve_timing_coefficients(result, "diff_sizing_coefficients")
    result["diff_sizing_coefficients"] = coefficients
    result.update(
        flow_kind="sizing",
        place_io_engine="ecc",
        timing_rc_mode=timing_rc_mode,
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
        gpugr_bottom_routing_layer=result.get("gpugr_bottom_routing_layer") or "MET2",
        gpugr_top_routing_layer=result.get("gpugr_top_routing_layer") or "MET5",
        gr_sizing_rrr_iters=3 if timing_rc_mode == "gr" else 0,
        enable_fillers=0,
        random_center_init_flag=0,
        legalize_flag=1,
        detailed_place_flag=0,
        detailed_place_engine="",
        diff_sizing_continuous_steps=continuous_steps,
        diff_sizing_terminal_gr_sta_enabled=int(bool(terminal_gr_sta_enabled)),
        diff_sizing_timing_rc_mode=timing_rc_mode,
        timing_wns_coeff=coefficients["wns"],
        timing_tns_coeff=coefficients["tns"],
        timing_cap_weight=coefficients["cap"],
        timing_slew_weight=coefficients["slew"],
        timing_grad_balance_weight=1.0,
        timing_grad_balance_target_ratio=0.0,
        timing_action_score_objective=score_objective,
    )
    if action_mode == "lut_action":
        result.update(
            sizing_parameterization="real_size",
            real_size_execution_mode="continuous_only",
            real_size_warmup_steps=0,
            continuous_size_dynamics_mode="none",
        )
    elif continuous_steps == 0:
        result.update(
            sizing_parameterization="logits",
            real_size_execution_mode="continuous_only",
            real_size_warmup_steps=0,
            continuous_size_dynamics_mode="discrete_gradient_topk",
        )
    stages = list(result.get("global_place_stages") or [{}])
    first_stage = dict(stages[0]) if isinstance(stages[0], dict) else {}
    stage_rounds = (
        sum(spec.rounds for spec in flows) if flows is not None else 50
    )
    first_stage.update(
        num_bins_x=512,
        num_bins_y=512,
        iteration=stage_rounds,
        optimizer="adam",
    )
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
    params, internal_buffering_keys = _apply_placement_buffering_profile(workspace, step, params)
    dreamplace_overrides = parameter_data.get("dreamplace")
    explicit_keys = set(dreamplace_overrides) if isinstance(dreamplace_overrides, dict) else set()
    explicit_keys.update(apply_direct_config_overrides({}, parameter_data))
    explicit_keys.update(internal_buffering_keys)
    if step.name == StepEnum.DIFF_OPT.value:
        params = prepare_diff_opt_drive_table(workspace, step, apply_diff_opt_defaults(params))
    elif step.name == StepEnum.DIFF_SIZING.value:
        params = _apply_diff_sizing_defaults(params, explicit_keys=explicit_keys)
    elif step.name == StepEnum.DIFF_BUFFERING.value:
        # Legacy workspaces retain the old step name, but execute the
        # placement-parasitic diff_opt controller and its canonical tuple
        # configuration.  Keep the old fields as aliases for migration.
        params = prepare_diff_opt_drive_table(workspace, step, apply_diff_opt_defaults(params))

    from dreamplace.flows.flow_config import resolve_flow_config

    params = resolve_flow_config(params, explicit_keys=explicit_keys)
    # Canonical profiles own defaults; explicit workspace values own the final
    # effective config and therefore must be replayed after profile expansion.
    params = apply_parameter_overrides(params, parameter_data)
    params = apply_direct_config_overrides(params, parameter_data)
    if step.name == StepEnum.DIFF_OPT.value:
        params = prepare_diff_opt_drive_table(workspace, step, apply_diff_opt_defaults(params))
    elif step.name == StepEnum.DIFF_SIZING.value:
        # Workspace-level placement values (density, padding and routability)
        # are intentionally not shared with the standalone sizing lane.
        params = _apply_diff_sizing_defaults(params, explicit_keys=explicit_keys)
    elif step.name == StepEnum.DIFF_BUFFERING.value:
        params = prepare_diff_opt_drive_table(workspace, step, apply_diff_opt_defaults(params))
    params = _set_step_fields(params, step)

    config_path = step_config_path(workspace, step)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    json_write(config_path, params)
