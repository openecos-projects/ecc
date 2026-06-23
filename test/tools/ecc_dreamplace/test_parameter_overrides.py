from chipcompiler.tools.ecc_dreamplace.parameter_overrides import (
    apply_parameter_overrides,
)


def test_flat_legacy_keys_map_to_dreamplace_fields():
    base = {
        "target_density": 0.8,
        "stop_overflow": 0.1,
        "cell_padding_x": 600,
        "routability_opt_flag": 0,
    }
    parameter_data = {
        "Target density": 0.65,
        "Target overflow": 0.05,
        "Cell padding x": 800,
        "Routability opt flag": 1,
    }

    result = apply_parameter_overrides(base, parameter_data)

    assert result["target_density"] == 0.65
    assert result["stop_overflow"] == 0.05
    assert result["cell_padding_x"] == 800
    assert result["routability_opt_flag"] == 1


def test_nested_dreamplace_overrides_are_applied():
    base = {"routability_opt_flag": 0, "target_density": 0.8}
    parameter_data = {
        "DreamPlace": {
            "routability_opt_flag": 1,
            "target_density": 0.7,
        },
    }

    result = apply_parameter_overrides(base, parameter_data)

    assert result["routability_opt_flag"] == 1
    assert result["target_density"] == 0.7


def test_nested_dreamplace_overrides_win_over_flat_keys():
    base = {"routability_opt_flag": 0}
    parameter_data = {
        "Routability opt flag": 1,
        "DreamPlace": {"routability_opt_flag": 0},
    }

    result = apply_parameter_overrides(base, parameter_data)

    assert result["routability_opt_flag"] == 0


def test_non_dict_dreamplace_value_keeps_flat_mappings():
    base = {"routability_opt_flag": 0}
    parameter_data = {
        "Routability opt flag": 1,
        "DreamPlace": "invalid",
    }

    result = apply_parameter_overrides(base, parameter_data)

    assert result["routability_opt_flag"] == 1


def test_apply_parameter_overrides_copies_inputs():
    base = {"nested": {"value": 1}}
    parameter_data = {"DreamPlace": {"list_value": [1, 2, 3]}}

    result = apply_parameter_overrides(base, parameter_data)

    result["nested"]["value"] = 2
    result["list_value"].append(4)

    assert base == {"nested": {"value": 1}}
    assert parameter_data == {"DreamPlace": {"list_value": [1, 2, 3]}}
