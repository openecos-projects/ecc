"""Static candidate knobs and runtime backend requirements."""

from dataclasses import asdict, dataclass
from typing import Any

from chipcompiler.data.types import StepEnum

from .candidate_artifacts import canonical_json_bytes, sha256_bytes


@dataclass(frozen=True)
class CandidateTargetBackend:
    """Backend requirements for one executable candidate target."""

    expected_tool: str
    adapter: str | None = None
    enabled: bool = True
    disabled_reason: str | None = None


@dataclass(frozen=True)
class CandidateKnob:
    knob_id: str
    target_step: str
    config_key: str
    json_path: tuple[str, ...]
    value_type: str
    minimum: int | float | None = None
    maximum: int | float | None = None
    pdk_attribute: str | None = None
    available: bool = True
    unavailable_reason: str | None = None


def _cts_number(name: str, minimum: float = 0.0, maximum: float | None = None) -> CandidateKnob:
    return CandidateKnob(
        f"cts.{name}", StepEnum.CTS.value, StepEnum.CTS.value, (name,), "number", minimum, maximum
    )


def _cts_uint(name: str, minimum: int = 1) -> CandidateKnob:
    return CandidateKnob(
        f"cts.{name}", StepEnum.CTS.value, StepEnum.CTS.value, (name,), "uint", minimum
    )


# The RPC-level "floorplan" target names the shared floorplan configuration,
# not a flow step; the backend tool and the phase input bind on its first
# sub-step when the flow runs the split phase.
FLOORPLAN_TARGET_FLOW_STEP = {StepEnum.FLOORPLAN.value: StepEnum.PRE_FLOORPLAN.value}


CANDIDATE_TARGET_BACKENDS: dict[str, CandidateTargetBackend] = {
    StepEnum.FLOORPLAN.value: CandidateTargetBackend("ecc"),
    StepEnum.PLACEMENT.value: CandidateTargetBackend("dreamplace"),
    StepEnum.CTS.value: CandidateTargetBackend("ecc"),
    StepEnum.LEGALIZATION.value: CandidateTargetBackend("dreamplace", "legalization_dreamplace"),
    StepEnum.ROUTING.value: CandidateTargetBackend("ecc"),
    StepEnum.FILLER.value: CandidateTargetBackend(
        "ecc",
        enabled=False,
        disabled_reason="ECC filler backend is not implemented in the current runtime",
    ),
}


CANDIDATE_KNOBS = (
    CandidateKnob(
        "floorplan.core_util",
        StepEnum.FLOORPLAN.value,
        "parameters",
        ("core", "utilitization"),
        "number",
        0.01,
        1.0,
    ),
    CandidateKnob(
        "floorplan.aspect_ratio",
        StepEnum.FLOORPLAN.value,
        "parameters",
        ("core", "aspect_ratio"),
        "number",
        0.1,
    ),
    CandidateKnob(
        "floorplan.core_margin",
        StepEnum.FLOORPLAN.value,
        "parameters",
        ("core", "margin"),
        "number_pair",
        0.0,
    ),
    CandidateKnob(
        "floorplan.tap_distance",
        StepEnum.FLOORPLAN.value,
        StepEnum.FLOORPLAN.value,
        ("Floorplan", "Tap distance"),
        "uint",
        0,
    ),
    CandidateKnob(
        "place.target_density",
        StepEnum.PLACEMENT.value,
        "dreamplace",
        ("target_density",),
        "number",
        0.1,
        0.95,
    ),
    CandidateKnob(
        "place.target_overflow",
        StepEnum.PLACEMENT.value,
        "dreamplace",
        ("stop_overflow",),
        "number",
        0.0,
        1.0,
    ),
    CandidateKnob(
        "place.cell_padding_x",
        StepEnum.PLACEMENT.value,
        "dreamplace",
        ("cell_padding_x",),
        "uint",
        0,
    ),
    CandidateKnob(
        "place.routability_opt",
        StepEnum.PLACEMENT.value,
        "dreamplace",
        ("routability_opt_flag",),
        "bool_int",
    ),
    CandidateKnob(
        "place.density_weight",
        StepEnum.PLACEMENT.value,
        "dreamplace",
        ("density_weight",),
        "number",
        0.0,
    ),
    CandidateKnob(
        "place.gp_noise_ratio",
        StepEnum.PLACEMENT.value,
        "dreamplace",
        ("gp_noise_ratio",),
        "number",
        0.0,
        1.0,
    ),
    CandidateKnob(
        "place.num_threads",
        StepEnum.PLACEMENT.value,
        "dreamplace",
        ("num_threads",),
        "uint",
        1,
    ),
    CandidateKnob(
        "place.timing_opt",
        StepEnum.PLACEMENT.value,
        "dreamplace",
        ("timing_opt_flag",),
        "bool_int",
        available=False,
        unavailable_reason="DreamPlace wrapper forces timing optimization off",
    ),
    CandidateKnob(
        "place.enable_net_weighting",
        StepEnum.PLACEMENT.value,
        "dreamplace",
        ("enable_net_weighting",),
        "bool_int",
        available=False,
        unavailable_reason="DreamPlace runtime does not consume net weighting",
    ),
    CandidateKnob(
        "place.pin2pin_weight",
        StepEnum.PLACEMENT.value,
        "dreamplace",
        ("pin2pin_weight",),
        "number",
        0.0,
        available=False,
        unavailable_reason="DreamPlace runtime does not consume pin-to-pin weighting",
    ),
    CandidateKnob(
        "route.bottom_layer",
        StepEnum.ROUTING.value,
        StepEnum.ROUTING.value,
        ("RT", "-bottom_routing_layer"),
        "string",
    ),
    CandidateKnob(
        "route.top_layer",
        StepEnum.ROUTING.value,
        StepEnum.ROUTING.value,
        ("RT", "-top_routing_layer"),
        "string",
    ),
    CandidateKnob(
        "route.thread_number",
        StepEnum.ROUTING.value,
        StepEnum.ROUTING.value,
        ("RT", "-thread_number"),
        "uint",
        1,
    ),
    CandidateKnob(
        "route.enable_timing",
        StepEnum.ROUTING.value,
        StepEnum.ROUTING.value,
        ("RT", "-enable_timing"),
        "bool_int",
    ),
    _cts_number("skew_bound", maximum=1.0),
    _cts_number("max_buf_tran"),
    _cts_number("root_input_slew"),
    _cts_number("max_sink_tran"),
    _cts_number("max_cap"),
    _cts_number("wirelength_unit_um"),
    _cts_number("wire_width"),
    _cts_uint("max_fanout"),
    CandidateKnob(
        "cts.routing_layer",
        StepEnum.CTS.value,
        StepEnum.CTS.value,
        ("routing_layer",),
        "uint_list",
        1,
    ),
    CandidateKnob(
        "cts.buffer_type",
        StepEnum.CTS.value,
        StepEnum.CTS.value,
        ("buffer_type",),
        "string_list",
        pdk_attribute="buffers",
    ),
    _cts_number("char_buf_redundancy_pct"),
    CandidateKnob(
        "cts.force_branch_buffer",
        StepEnum.CTS.value,
        StepEnum.CTS.value,
        ("force_branch_buffer",),
        "bool",
    ),
    _cts_number("htree_topology_tolerance"),
    CandidateKnob(
        "cts.enable_analytical_htree",
        StepEnum.CTS.value,
        StepEnum.CTS.value,
        ("enable_analytical_htree",),
        "bool",
    ),
    CandidateKnob(
        "cts.enable_sink_clustering",
        StepEnum.CTS.value,
        StepEnum.CTS.value,
        ("enable_sink_clustering",),
        "bool",
    ),
    CandidateKnob(
        "cts.max_length",
        StepEnum.CTS.value,
        StepEnum.CTS.value,
        ("max_length",),
        "number",
        0.0,
        available=False,
        unavailable_reason="iCTS does not accept max_length",
    ),
    CandidateKnob(
        "cts.use_netlist",
        StepEnum.CTS.value,
        StepEnum.CTS.value,
        ("use_netlist",),
        "string",
        available=False,
        unavailable_reason="iCTS does not accept use_netlist",
    ),
    CandidateKnob(
        "cts.net_list",
        StepEnum.CTS.value,
        StepEnum.CTS.value,
        ("net_list",),
        "string_list",
        available=False,
        unavailable_reason="iCTS does not accept net_list",
    ),
)


def candidate_knob_registry() -> tuple[CandidateKnob, ...]:
    return tuple(knob for knob in CANDIDATE_KNOBS if knob.available)


def candidate_capability_registry() -> tuple[CandidateKnob, ...]:
    return CANDIDATE_KNOBS


def candidate_registry_digest() -> str:
    payload = [asdict(knob) for knob in sorted(CANDIDATE_KNOBS, key=lambda item: item.knob_id)]
    return sha256_bytes(canonical_json_bytes(payload))


def candidate_target_backend(workspace: Any, target_step: str) -> dict[str, Any]:
    """Describe whether the workspace's configured tool can execute a candidate."""
    specification = CANDIDATE_TARGET_BACKENDS.get(target_step)
    actual_tool = _workspace_target_tool(workspace, target_step)
    if specification is None:
        return {
            "tool": actual_tool,
            "expected_tool": None,
            "available": False,
            "reason": f"unsupported candidate target: {target_step}",
        }

    backend: dict[str, Any] = {
        "tool": actual_tool,
        "expected_tool": specification.expected_tool,
    }
    if specification.adapter is not None:
        backend["adapter"] = specification.adapter
    if not specification.enabled:
        backend.update(
            available=False,
            reason=specification.disabled_reason,
        )
        return backend
    if actual_tool is None:
        backend.update(
            available=False,
            reason=f"workspace does not declare a unique {target_step} tool",
        )
        return backend
    if actual_tool != specification.expected_tool:
        backend.update(
            available=False,
            reason=(
                f"workspace {target_step} tool {actual_tool!r} does not support "
                f"the required {specification.expected_tool!r} candidate backend"
            ),
        )
        return backend
    backend["available"] = True
    return backend


def _workspace_target_tool(workspace: Any, target_step: str) -> str | None:
    flow = getattr(workspace, "flow", None)
    flow_data = getattr(flow, "data", None)
    if not isinstance(flow_data, dict):
        return None
    steps = flow_data.get("steps")
    if not isinstance(steps, list):
        return None

    def tools_for(step_name: str) -> list[str]:
        return [
            step["tool"]
            for step in steps
            if isinstance(step, dict)
            and step.get("name") == step_name
            and isinstance(step.get("tool"), str)
            and step["tool"]
        ]

    matches = tools_for(target_step)
    if not matches and target_step in FLOORPLAN_TARGET_FLOW_STEP:
        matches = tools_for(FLOORPLAN_TARGET_FLOW_STEP[target_step])
    return matches[0] if len(matches) == 1 else None
