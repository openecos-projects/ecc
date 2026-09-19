#!/usr/bin/env python

from chipcompiler.data.param_keys import (
    AGENT_KNOB_MAP,
    DIE_AREA_MODE_TO_DIE_BUILDER_MODE,
    DISPLAY_KEY_MAP,
    AgentKnob,
    display_key_for,
    knob_id_for,
)
from chipcompiler.data.parameter_schema import is_known_key


def test_every_mapped_spec_key_exists_in_param_registry():
    spec_keys = set(DISPLAY_KEY_MAP.values()) | {knob.spec_key for knob in AGENT_KNOB_MAP.values()}
    assert spec_keys
    unknown = {key for key in spec_keys if not is_known_key(key)}
    assert unknown == set()


def test_display_key_and_knob_id_lookups_are_inverse_to_the_maps():
    for display, spec in DISPLAY_KEY_MAP.items():
        assert display_key_for(spec) == display
    for knob_id, knob in AGENT_KNOB_MAP.items():
        assert knob_id_for(knob.spec_key) == knob_id
    assert display_key_for("sta.max_paths") is None
    assert knob_id_for("sta.max_paths") is None


def test_knob_value_transforms_follow_the_agent_contract():
    by_id = {knob_id: knob for knob_id, knob in AGENT_KNOB_MAP.items()}
    enable_timing = by_id["route.enable_timing"].value_transform
    routability_opt = by_id["place.routability_opt"].value_transform
    assert enable_timing is not None and routability_opt is not None
    assert enable_timing(value=True) == "1"
    assert enable_timing(value=False) == "0"
    assert routability_opt(value=True) == 1
    assert routability_opt(value=False) == 0
    assert by_id["cts.skew_bound"].value_transform(0.12) == "0.12"
    assert by_id["route.thread_number"].value_transform(32) == "32"
    assert by_id["design.frequency_max"].value_transform is None
    assert AgentKnob("place.num_threads").value_transform is None


def test_die_area_mode_values_select_die_builder_mode():
    assert DIE_AREA_MODE_TO_DIE_BUILDER_MODE["width_height"] == "die_size"
    assert DIE_AREA_MODE_TO_DIE_BUILDER_MODE["utilitization_margin"] == "die_util"


def test_parameter_catalog_records_carry_display_key_and_knob_id():
    from chipcompiler.engine.workspace_spec import describe_workspace_spec

    catalog = describe_workspace_spec()["parameterCatalog"]
    assert catalog
    for entry in catalog:
        assert entry["display_key"] == display_key_for(entry["id"])
        assert entry["knob_id"] == knob_id_for(entry["id"])
    by_id = {entry["id"]: entry for entry in catalog}
    assert by_id["design.frequency_mhz"]["display_key"] == "frequency_max"
    assert by_id["design.frequency_mhz"]["knob_id"] == "design.frequency_max"
    assert by_id["floorplan.core_util"]["display_key"] == "utilization"
    assert by_id["route.RT.-enable_timing"]["knob_id"] == "route.enable_timing"
    assert by_id["sta.max_paths"]["display_key"] is None
    assert by_id["sta.max_paths"]["knob_id"] is None
