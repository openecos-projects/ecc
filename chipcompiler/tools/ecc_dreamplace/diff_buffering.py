"""Standalone typed candidate buffering and its physical terminal boundary."""

import math
from copy import copy, deepcopy
from dataclasses import asdict, is_dataclass
from pathlib import Path

from chipcompiler.data import Workspace, WorkspaceStep
from chipcompiler.utility import json_write

from .discrete_timing_config import apply_discrete_timing_defaults
from .timing_coefficients import resolve_timing_coefficients


def _json_safe(value):
    """Normalize terminal diagnostics before writing JSON artifacts."""

    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "detach"):
        detached = value.detach()
        return detached.cpu().tolist() if detached.numel() != 1 else float(detached.cpu().item())
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def resolve_diff_buffering_settings(params):
    rounds = params.get("diff_buffering_rounds", 10)
    fraction = params.get("diff_buffering_selection_fraction", 0.001)
    if isinstance(rounds, bool) or not isinstance(rounds, int) or not 1 <= rounds <= 1000:
        raise ValueError("diff_buffering_rounds must be an integer in [1, 1000]")
    if (
        isinstance(fraction, bool)
        or not isinstance(fraction, (int, float))
        or not math.isfinite(fraction)
        or not 0 < fraction <= 1
    ):
        raise ValueError("diff_buffering_selection_fraction must be in (0, 1]")
    coefficients = resolve_timing_coefficients(params, "diff_buffering_coefficients")
    return rounds, fraction, coefficients


def apply_diff_buffering_defaults(params: dict) -> dict:
    result = deepcopy(params)
    rounds, fraction, coefficients = resolve_diff_buffering_settings(result)
    result = apply_discrete_timing_defaults(result, coefficients)
    result.update(
        diff_buffering_coefficients=coefficients,
        flow_kind="buffering",
        placement_sizing_mode="place_only",
        sizing_parameterization="logits",
        continuous_size_dynamics_mode="none",
        buffering_continuous_steps=rounds,
        buffering_route_b_selection_fraction=fraction,
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


def finalize_diff_buffering(
    engine,
    *,
    flow_kind: str = "buffering",
    summary_stem: str = "diff_buffering",
) -> dict:
    from dreamplace.NonLinearPlace import NonLinearPlace

    lane = engine.placer.last_buffering_lane_summary
    diff_opt_controller = getattr(engine.placer, "diff_opt_controller", None)
    if lane["status"] != "completed":
        raise RuntimeError(f"{flow_kind} did not complete its standalone candidate lane")
    commit = lane["commit"]
    if commit["status"] not in {"accepted", "skipped"}:
        raise RuntimeError(f"{flow_kind} native commit failed: {commit}")
    refresh = engine._physical_mutation_backend().refresh(
        refresh_mode="full_rebuild", rebuild_mode="full_rebuild"
    )
    if refresh["status"] != "ok":
        raise RuntimeError(f"{flow_kind} topology refresh failed: {refresh}")

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
        raise RuntimeError(f"{flow_kind} terminal placement is not legal")
    _, _, engine.metrics = placer.run_sta_only(params, engine.placedb)
    timing = engine.metrics["timing_stage_summary"]["sta"]
    if not all(math.isfinite(float(timing[key])) for key in ("wns", "tns")):
        raise RuntimeError(f"{flow_kind} terminal STA is nonfinite")
    summary = {
        "status": "ok",
        "flow_kind": flow_kind,
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
        "refresh_counts": {
            "geometry_refresh_count": int(
                getattr(diff_opt_controller, "geometry_refresh_count", 0)
            ),
            "timing_refresh_count": int(getattr(diff_opt_controller, "timing_refresh_count", 0)),
            "full_rebuild_count": 1,
        },
    }
    summary = _json_safe(summary)
    json_write(Path(engine.params.result_dir) / f"{summary_stem}_summary.json", summary)
    engine.last_run_result = summary
    return summary
