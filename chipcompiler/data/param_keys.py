"""Single authority for GUI display keys and Agent knob ids.

Studio derives its workspace-creation wizard mapping, step-config panels, and
the Agent knob whitelist from one parameter catalog (RPC
``workspace_spec.describe`` and step-configuration reads). The catalog records
carry a ``display_key`` and a ``knob_id`` for each canonical parameter, built
from the tables in this module, so the GUI never hardcodes its own key
mapping.

Display keys use the corrected spelling ``utilization``. Older GUI builds
emit the misspelling ``utilitization`` or the alias ``core_utilization`` for
the same field; both denote ``DISPLAY_KEY_MAP["utilization"]``.

The legacy-tree geometry aliases consumed by
:mod:`chipcompiler.data.parameter_keys` (``die_width``/``die_height``/
``utilitization``/``margin`` folded into the ``die``/``core`` subtrees of
``workspace.parameters.data``) are a different vocabulary and stay there;
this module maps display keys onto the flat ``PARAM_REGISTRY`` spec keys.

Value-shape notes mirrored from the GUI seed data:

- ``margin`` is a single scalar the GUI expands to ``[margin, margin]``.
- ``die_area_mode`` selects the die-builder strategy; see
  :data:`DIE_AREA_MODE_TO_DIE_BUILDER_MODE`.
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentKnob:
    """One Agent-adjustable knob: knob id to canonical spec key plus value transform."""

    spec_key: str
    value_transform: Callable[[object], object] | None = None


def _number_to_string(value: object) -> str:
    return str(value)


def _boolean_to_int(value: object) -> int:
    return 1 if value else 0


def _boolean_to_digit(value: object) -> str:
    return "1" if value else "0"


DISPLAY_KEY_MAP: dict[str, str] = {
    "frequency_max": "design.frequency_mhz",
    "utilization": "floorplan.core_util",
    "margin": "floorplan.core_margin",
    "die_width": "floorplan.die_builder.die_size.width_micron",
    "die_height": "floorplan.die_builder.die_size.height_micron",
    "die_area_mode": "floorplan.die_builder.mode",
    "max_fanout": "cts.max_fanout",
    "target_density": "place.target_density",
    "target_overflow": "place.target_overflow",
}

DIE_AREA_MODE_TO_DIE_BUILDER_MODE: dict[str, str] = {
    "width_height": "die_size",
    "utilitization_margin": "die_util",
}

AGENT_KNOB_MAP: dict[str, AgentKnob] = {
    "design.frequency_max": AgentKnob("design.frequency_mhz"),
    "floorplan.utilitization": AgentKnob("floorplan.core_util"),
    "floorplan.aspect_ratio": AgentKnob("floorplan.aspect_ratio"),
    "floorplan.die_width": AgentKnob("floorplan.die_builder.die_size.width_micron"),
    "floorplan.die_height": AgentKnob("floorplan.die_builder.die_size.height_micron"),
    "floorplan.global_right_padding": AgentKnob("place.global_right_padding"),
    "place.target_density": AgentKnob("place.target_density"),
    "place.target_overflow": AgentKnob("place.target_overflow"),
    "place.cell_padding_x": AgentKnob("place.cell_padding_x"),
    "place.routability_opt": AgentKnob("place.routability_opt", _boolean_to_int),
    "cts.max_fanout": AgentKnob("cts.max_fanout"),
    "route.bottom_layer": AgentKnob("route.bottom_layer"),
    "route.top_layer": AgentKnob("route.top_layer"),
    "place.density_weight": AgentKnob("place.density_weight"),
    "place.gp_noise_ratio": AgentKnob("place.gp_noise_ratio"),
    "place.num_threads": AgentKnob("place.num_threads"),
    "cts.skew_bound": AgentKnob("cts.skew_bound", _number_to_string),
    "cts.max_buf_tran": AgentKnob("cts.max_buf_tran", _number_to_string),
    "cts.root_input_slew": AgentKnob("cts.root_input_slew", _number_to_string),
    "cts.max_sink_tran": AgentKnob("cts.max_sink_tran", _number_to_string),
    "cts.max_cap": AgentKnob("cts.max_cap", _number_to_string),
    "cts.wirelength_iterations": AgentKnob("cts.wirelength_iterations", _number_to_string),
    "cts.slew_steps": AgentKnob("cts.slew_steps", _number_to_string),
    "cts.cap_steps": AgentKnob("cts.cap_steps", _number_to_string),
    "cts.routing_layer": AgentKnob("cts.routing_layer"),
    "cts.buffer_type": AgentKnob("cts.buffer_type"),
    "route.thread_number": AgentKnob("route.RT.-thread_number", _number_to_string),
    "route.enable_timing": AgentKnob("route.RT.-enable_timing", _boolean_to_digit),
}

_DISPLAY_KEY_BY_SPEC = {spec: display for display, spec in DISPLAY_KEY_MAP.items()}
_KNOB_ID_BY_SPEC = {knob.spec_key: knob_id for knob_id, knob in AGENT_KNOB_MAP.items()}


def display_key_for(spec_key: str) -> str | None:
    """Canonical GUI display key for a spec key, or None when the GUI has none."""
    return _DISPLAY_KEY_BY_SPEC.get(spec_key)


def knob_id_for(spec_key: str) -> str | None:
    """Agent knob id for a spec key, or None when the Agent cannot adjust it."""
    return _KNOB_ID_BY_SPEC.get(spec_key)
