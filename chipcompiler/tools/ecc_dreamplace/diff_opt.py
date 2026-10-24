"""ECC ``diff_opt`` step configuration and terminal bridge.

``diff_opt`` replaces the historical ``diff_buffering`` step.  It owns the
placement-parasitic sizing/buffering/joint configuration, while the existing
``diff_sizing`` step keeps its independent GR/RRR configuration.
"""

from copy import deepcopy
from pathlib import Path

from chipcompiler.utility import json_write

from .diff_buffering import prepare_drive_table, resolve_diff_buffering_settings
from .discrete_timing_config import apply_discrete_timing_defaults
from .timing_coefficients import resolve_timing_coefficients

_LEGACY_BUFFERING_ROUNDS = 10
_LEGACY_BUFFERING_COEFFICIENTS = {
    "wns": 500.0,
    "tns": 5.0,
    "cap": 1.0,
    "slew": 1.0,
}


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


def _validate_explicit_legacy_conflict(params, *, mode, flows_value):
    """Reject non-default legacy buffering settings beside canonical flows.

    The resolved parameter object always contains legacy defaults, so defaults
    are intentionally tolerated. A non-default legacy round/coefficient is an
    explicit old contract and must not silently override a canonical flow list.
    """

    from dreamplace.flows.diff_opt_spec import TimingCoefficients

    if flows_value is None:
        return
    rounds = params.get("diff_buffering_rounds", _LEGACY_BUFFERING_ROUNDS)
    coefficients = resolve_timing_coefficients(params, "diff_buffering_coefficients")
    rounds_changed = rounds != _LEGACY_BUFFERING_ROUNDS
    coefficients_changed = coefficients != _LEGACY_BUFFERING_COEFFICIENTS
    if not (rounds_changed or coefficients_changed):
        return
    if mode != "buffering":
        raise ValueError(
            "diff_optimization_flows conflicts with explicit legacy "
            "diff_buffering settings; remove diff_buffering_rounds/coefficients"
        )
    first = flows_value[0] if isinstance(flows_value, (list, tuple)) and flows_value else None
    if not isinstance(first, (list, tuple)) or len(first) != 3 or str(first[0]).lower() != "bf":
        raise ValueError(
            "diff_optimization_flows conflicts with explicit legacy "
            "diff_buffering settings; the canonical buffering flow must be used"
        )
    if rounds_changed and first[1] != rounds:
        raise ValueError("diff_optimization_flows conflicts with diff_buffering_rounds")
    canonical_coefficients = TimingCoefficients.from_value(first[2]).to_dict()
    if coefficients_changed and canonical_coefficients != coefficients:
        raise ValueError("diff_optimization_flows conflicts with diff_buffering_coefficients")


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
        buffering_route_b_selection_fraction=result.get("diff_buffering_selection_fraction", 0.001),
        # The four-action LUT path is owned by standalone diff_sizing; the
        # placement-parasitic diff_opt lane keeps its original discrete path.
        timing_action_gradient_mode="off",
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
    _validate_explicit_legacy_conflict(result, mode=mode.strip().lower(), flows_value=flows_value)
    if flows_value is None and mode == "buffering":
        legacy_rounds, _fraction, legacy_coefficients = resolve_diff_buffering_settings(result)
        flows_value = [["bf", legacy_rounds, legacy_coefficients]]
    mode, flows = parse_diff_opt_flows(mode, flows_value)
    result = _apply_common_diff_opt_defaults(result, mode=mode, flows=flows)

    if any(spec.action == "bf" for spec in flows):
        _rounds, fraction, _coefficients = resolve_diff_buffering_settings(result)
        result["buffering_route_b_selection_fraction"] = fraction
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
