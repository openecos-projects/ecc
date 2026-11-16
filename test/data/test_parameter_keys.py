#!/usr/bin/env python

from chipcompiler.data.parameter_keys import (
    normalize_key,
    normalize_keys,
    normalize_parameter_dict,
)


def test_normalize_key_mechanical_rule():
    assert normalize_key("Frequency max [MHz]") == "frequency_max"
    assert normalize_key("Max fanout") == "max_fanout"
    assert normalize_key("Top module") == "top_module"
    assert normalize_key("PDK") == "pdk"
    assert normalize_key("PDN") == "pdn"
    assert normalize_key("DreamPlace") == "dreamplace"
    assert normalize_key("STA max paths") == "sta_max_paths"
    assert normalize_key("Cell padding x") == "cell_padding_x"
    assert normalize_key("Routability opt flag") == "routability_opt_flag"
    assert normalize_key("Bounding box") == "bounding_box"
    assert normalize_key("Aspect ratio") == "aspect_ratio"
    # Already-canonical keys are untouched.
    assert normalize_key("frequency_max") == "frequency_max"
    assert normalize_key("die") == "die"


def test_normalize_parameter_dict_preserves_internal_input_mode():
    assert normalize_parameter_dict({"_input_mode": "postSynthesis"}) == {
        "_input_mode": "postSynthesis"
    }


def test_normalize_keys_recurses_into_nested_dicts_and_lists():
    legacy = {
        "Die": {"Size": [100, 200], "Area": 0},
        "Floorplan": {
            "Tracks": [{"x start": 0, "x step": 420}],
            "Auto place pin": {"layer": "Metal3"},
        },
    }
    assert normalize_keys(legacy) == {
        "die": {"size": [100, 200], "area": 0},
        "floorplan": {
            "tracks": [{"x_start": 0, "x_step": 420}],
            "auto_place_pin": {"layer": "Metal3"},
        },
    }


def test_normalize_keys_does_not_mutate_input():
    legacy = {"Top module": "gcd"}
    normalize_keys(legacy)
    assert legacy == {"Top module": "gcd"}


def test_normalize_keys_is_idempotent():
    legacy = {
        "Frequency max [MHz]": 100,
        "Core": {"Utilitization": 0.4, "Margin": [2, 2]},
    }
    once = normalize_keys(legacy)
    assert normalize_keys(once) == once


def test_normalize_keys_collision_long_key_wins(caplog):
    payload = {"Frequency max [MHz]": 100, "frequency_max": 200}
    with caplog.at_level("WARNING"):
        result = normalize_keys(payload)
    assert result == {"frequency_max": 100}
    assert any("frequency_max" in record.message for record in caplog.records)


def test_normalize_parameter_dict_preserves_reserved_payloads():
    payload = {
        "config_overrides": {
            "CTS": {"skew_bound": "0.1"},
            "route": {"RT": {"-thread_number": "16"}},
        },
        "workspace_param_overrides": [
            {
                "key": "sta.signoff",
                "baseline": [{"MAX": ["Cworst"]}],
                "value": [{"MIN": ["Cbest"]}],
            }
        ],
        "DreamPlace": {"Target Density": 0.5},
    }
    result = normalize_parameter_dict(payload)
    # Reserved payloads fold onto their canonical key but keep every literal
    # identifier inside: tool config keys, JSON paths, corner names.
    assert result["config_overrides"] == {
        "CTS": {"skew_bound": "0.1"},
        "route": {"RT": {"-thread_number": "16"}},
    }
    assert result["workspace_param_overrides"] == [
        {
            "key": "sta.signoff",
            "baseline": [{"MAX": ["Cworst"]}],
            "value": [{"MIN": ["Cbest"]}],
        }
    ]
    # Ordinary keys still normalize.
    assert result["dreamplace"] == {"target_density": 0.5}
