"""ECC ``diff_opt`` step configuration and terminal bridge.

``diff_opt`` owns the placement-parasitic optimization lane. It owns the
placement-parasitic sizing/buffering/joint configuration, while the existing
``diff_sizing`` step keeps its independent GR/RRR configuration.
"""

from copy import deepcopy
from pathlib import Path

from chipcompiler.utility import json_write

from .diff_buffering import prepare_drive_table
from .discrete_timing_config import apply_discrete_timing_defaults


def _validate_parasitic_source(params):
    source = (
        str(params.get("diff_opt_parasitic_source", "placement") or "placement").strip().lower()
    )
    if source != "placement":
        raise ValueError(
            "diff_opt supports only placement parasitic parameters; "
            f"got diff_opt_parasitic_source={source!r}"
        )
    params["diff_opt_parasitic_source"] = "placement"


def _apply_common_diff_opt_defaults(result, *, mode, flows):
    from dreamplace.flows.diff_opt_spec import DIFF_OPT_SCHEMA_VERSION

    result = apply_discrete_timing_defaults(result, flows[0].coefficients.to_dict())
    result.update(
        diff_opt_enabled=1,
        diff_opt_mode=mode,
        diff_opt_schema_version=DIFF_OPT_SCHEMA_VERSION,
        diff_optimization_mode=mode,
        diff_optimization_flows=[spec.to_list() for spec in flows],
        diff_opt_parasitic_source="placement",
        real_size_execution_mode="continuous_only",
        real_size_warmup_steps=0,
        sizing_parameterization="real_size",
        continuous_size_dynamics_mode="none",
        joint_quality_profile="",
        buffering_continuous_steps=flows[0].steps,
        buffering_route_b_selection_fraction=0.001,
        timing_action_gradient_mode=result.get("timing_action_gradient_mode", "lut_action"),
    )
    if mode == "buffering":
        result.update(flow_kind="buffering", placement_sizing_mode="place_only")
    elif mode == "sizing":
        result.update(flow_kind="sizing", placement_sizing_mode="size_only")
    else:
        result.update(flow_kind="placement", placement_sizing_mode="size_only")
    return result


def apply_diff_opt_defaults(params: dict) -> dict:
    """Resolve the placement-parasitic ``diff_opt`` profile."""

    from dreamplace.flows.diff_opt_spec import parse_diff_opt_flows

    result = deepcopy(params)
    _validate_parasitic_source(result)
    mode = str(result.get("diff_optimization_mode", "buffering") or "buffering").strip().lower()
    flows_value = result.get("diff_optimization_flows")
    mode, flows = parse_diff_opt_flows(mode, flows_value)
    result = _apply_common_diff_opt_defaults(result, mode=mode, flows=flows)

    if mode == "buffering":
        result.update(sizing_parameterization="logits", global_place_flag=1)
    elif mode == "sizing":
        result.update(
            gr_sizing_rrr_iters=0, gpugr_backend="none", global_place_flag=1, legalize_flag=1
        )
    else:
        result.update(global_place_flag=1)

    # All diff_opt modes execute discrete tuple rounds in the standalone
    # controller.  The GP stage only constructs the timing model and therefore
    # must never move placement coordinates.
    stages = list(result.get("global_place_stages") or [{}])
    stage = dict(stages[0]) if isinstance(stages[0], dict) else {}
    stage.update(num_bins_x=512, num_bins_y=512, iteration=0, optimizer="adam")
    result["global_place_stages"] = [stage]
    return result


def finalize_diff_opt(engine) -> dict:
    """Commit the one final request and run the existing terminal boundary."""

    from .diff_buffering import finalize_diff_buffering

    controller = getattr(getattr(engine, "placer", None), "diff_opt_controller", None)
    result = finalize_diff_buffering(
        engine,
        flow_kind="diff_opt",
        summary_stem="diff_opt",
    )
    result = dict(result)
    result["diff_opt_parasitic_source"] = "placement"
    if controller is not None:
        result["diff_opt_flow_summary"] = {
            "phase_count": int(getattr(controller, "phase_count", 0)),
            "geometry_refresh_count": int(getattr(controller, "geometry_refresh_count", 0)),
            "timing_refresh_count": int(getattr(controller, "timing_refresh_count", 0)),
            "full_rebuild_count": 1,
            "summary_path": getattr(controller, "summary_path", None),
        }
    result_dir = Path(engine.params.result_dir)
    json_write(result_dir / "diff_opt_summary.json", result)
    engine.last_run_result = result
    return result


__all__ = [
    "apply_diff_opt_defaults",
    "finalize_diff_opt",
    "prepare_drive_table",
]
