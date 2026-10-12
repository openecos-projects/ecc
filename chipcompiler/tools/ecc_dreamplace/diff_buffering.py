"""Standalone typed candidate buffering and its physical terminal boundary."""

import math
from copy import copy, deepcopy
from pathlib import Path

from chipcompiler.data import Workspace, WorkspaceStep
from chipcompiler.utility import json_write

from .timing_coefficients import resolve_timing_coefficients


def apply_diff_buffering_defaults(params: dict) -> dict:
    result = deepcopy(params)
    rounds = result.get("diff_buffering_rounds", 10)
    fraction = result.get("diff_buffering_selection_fraction", 0.003)
    if isinstance(rounds, bool) or not isinstance(rounds, int) or not 1 <= rounds <= 1000:
        raise ValueError("diff_buffering_rounds must be an integer in [1, 1000]")
    if (
        isinstance(fraction, bool)
        or not isinstance(fraction, (int, float))
        or not math.isfinite(fraction)
        or not 0 < fraction <= 1
    ):
        raise ValueError("diff_buffering_selection_fraction must be in (0, 1]")
    coefficients = resolve_timing_coefficients(result, "diff_buffering_coefficients")
    # Discrete candidates have no continuous learning-rate parameter.
    result.pop("buffering_continuous_lr", None)
    result.update(
        diff_buffering_coefficients=coefficients,
        flow_kind="buffering",
        place_io_engine="ecc",
        gpu=0,
        placement_sizing_mode="place_only",
        sizing_parameterization="logits",
        continuous_size_dynamics_mode="none",
        real_size_execution_mode="continuous_only",
        real_size_warmup_steps=0,
        random_center_init_flag=0,
        gp_noise_ratio=0.0,
        enable_fillers=0,
        cell_padding_x=0,
        cell_padding_y=0,
        auto_adjust_bins=0,
        num_bins_x=512,
        num_bins_y=512,
        route_num_bins_x=512,
        route_num_bins_y=512,
        global_place_flag=1,
        legalize_flag=0,
        detailed_place_flag=0,
        plot_flag=0,
        timing_opt_enabled=0,
        timing_opt_buffering_enabled=0,
        timing_opt_flag=0,
        routability_opt_flag=0,
        l_shape_routability_flag=0,
        adjust_gpugr_area_flag=0,
        gpugr_final_eval_flag=0,
        enable_net_weighting=0,
        pin2pin_net_weighting=0,
        with_sta=1,
        timing_eval_flag=1,
        timing_rc_mode="placement",
        timing_propagation_device="cpu",
        production_fast_loop=True,
        timing_lut_2d_native_op="auto",
        size_interpolated_pin_native_op="auto",
        timing_surrogate_mode="lut_only",
        cell_model_schema="main_id_arc_offset_piecewise_linear",
        piecewise_gradient_mode="native_piecewise",
        differentiable_timing_obj=1,
        diff_timing_driven_placement=1,
        timing_objective_lane="timing_slew_cap",
        timing_wns_coeff=coefficients["wns"],
        timing_tns_coeff=coefficients["tns"],
        timing_cap_weight=coefficients["cap"],
        timing_slew_weight=coefficients["slew"],
        timing_grad_balance_target_ratio=0.0,
        timing_grad_balance_weight=1.0,
        timing_coeff_growth_factor=1.0,
        buffering_mode="candidate",
        buffering_candidate_strategy="discrete_net_gradient",
        buffering_candidate_drive_type_mode="four_strength_table",
        buffering_candidate_policy="segment_only",
        buffering_include_tree_node_candidates=0,
        buffering_segment_strategy="continuous",
        buffering_fixed_buffer_master="",
        buffering_fixed_bsu_index=None,
        buffering_continuous_relaxed_optimization=1,
        buffering_segment_count_tns_gradient=0,
        buffering_max_repeaters_per_segment=3,
        buffering_continuous_steps=rounds,
        buffering_route_b_selection_fraction=fraction,
        buffering_segment_count_timing_backend="cpp_cpu_segment_transfer_explicit_autograd",
        buffering_segment_transfer_backend="segment_transfer_native",
        buffering_discrete_count_proximal_lambda=0.0,
        buffering_commit_enabled=1,
        joint_post_commit_continue=False,
        joint_segment_virtual_density_enabled=0,
    )
    # The existing buffering lane returns before the GP optimizer loop; this
    # one-stage entry constructs its shared timing model without moving cells.
    stage = dict(result["global_place_stages"][0])
    stage.update(iteration=1, num_bins_x=512, num_bins_y=512)
    result["global_place_stages"] = [stage]
    return result


def prepare_drive_table(workspace: Workspace, step: WorkspaceStep, params: dict) -> dict:
    from dreamplace.flows.buffer_drive_table import build_drive_strength_table

    directory = Path(step.data.workdir_for(step.name))
    table_path = directory / "buffer_drive_strength.json"
    table = build_drive_strength_table(
        workspace.pdk.name,
        workspace.pdk.buffers,
        Path(workspace.directory) / "home/engineering-snapshot.json",
    )
    directory.mkdir(parents=True, exist_ok=True)
    json_write(table_path, table)
    return params | {
        "buffering_candidate_drive_strength_table": str(table_path),
        "buffering_output_dir": str(directory / "buffering_inner_loop"),
    }


def finalize_diff_buffering(engine) -> dict:
    from dreamplace.NonLinearPlace import NonLinearPlace

    lane = engine.placer.last_buffering_lane_summary
    if lane["status"] != "completed":
        raise RuntimeError("diff_buffering did not complete its standalone candidate lane")
    commit = lane["commit"]
    if commit["status"] not in {"accepted", "skipped"}:
        raise RuntimeError(f"diff_buffering native commit failed: {commit}")
    refresh = engine._physical_mutation_backend().refresh(
        refresh_mode="full_rebuild", rebuild_mode="full_rebuild"
    )
    if refresh["status"] != "ok":
        raise RuntimeError(f"diff_buffering topology refresh failed: {refresh}")

    params = copy(engine.params)
    params.flow_kind = "placement"
    params.global_place_flag = 0
    params.legalize_flag = 1
    params.differentiable_timing_obj = 0
    params.diff_timing_driven_placement = 0
    params.enable_relaxed_buffer_timing = False
    params.buffering_continuous_relaxed_optimization = 0
    params.timing_aggregation_mode = "hard"
    params.result_dir = str(Path(engine.params.result_dir) / "terminal")
    Path(params.result_dir).mkdir(parents=True, exist_ok=True)
    engine.placedb.cooptimization_geometry = None
    placer = NonLinearPlace(params, engine.placedb, None)
    engine.placer = placer
    engine.rsmt, engine.hpwl, engine.metrics = placer(params, engine.placedb)
    if not placer.op_collections.legality_check_op(placer.pos[0]):
        raise RuntimeError("diff_buffering terminal placement is not legal")
    _, _, engine.metrics = placer.run_sta_only(params, engine.placedb)
    timing = engine.metrics["timing_stage_summary"]["sta"]
    if not all(math.isfinite(float(timing[key])) for key in ("wns", "tns")):
        raise RuntimeError("diff_buffering terminal STA is nonfinite")
    summary = {
        "status": "ok",
        "flow_kind": "buffering",
        "legal": True,
        "new_gp_optimizer_steps": 0,
        "sizing_steps": 0,
        "virtual_count": 0,
        "commit": commit,
        "refresh": refresh,
        "buffering": lane["inner_loop"],
        "final_timing": timing,
        "hpwl": engine.hpwl,
        "rsmt": engine.rsmt,
    }
    json_write(Path(engine.params.result_dir) / "diff_buffering_summary.json", summary)
    engine.last_run_result = summary
    return summary
