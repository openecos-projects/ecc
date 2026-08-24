from chipcompiler.tools.ecc_dreamplace.parameter_overrides import (
    apply_parameter_overrides,
)


def _alternate_flag(value):
    return 0 if value else 1


def _alternate_float(value):
    return 0.65 if value != 0.65 else 0.7


def test_flat_keys_map_to_dreamplace_fields(dreamplace_default_config):
    parameter_data = {
        "target_density": _alternate_float(dreamplace_default_config["target_density"]),
        "target_overflow": _alternate_float(dreamplace_default_config["stop_overflow"]),
        "cell_padding_x": dreamplace_default_config["cell_padding_x"] + 500,
        "routability_opt_flag": _alternate_flag(dreamplace_default_config["routability_opt_flag"]),
    }

    result = apply_parameter_overrides(dreamplace_default_config, parameter_data)

    assert result["target_density"] == parameter_data["target_density"]
    assert result["stop_overflow"] == parameter_data["target_overflow"]
    assert result["cell_padding_x"] == parameter_data["cell_padding_x"]
    assert result["routability_opt_flag"] == parameter_data["routability_opt_flag"]


def test_nested_dreamplace_overrides_are_applied(dreamplace_default_config):
    overrides = {
        "routability_opt_flag": _alternate_flag(dreamplace_default_config["routability_opt_flag"]),
        "target_density": _alternate_float(dreamplace_default_config["target_density"]),
    }
    parameter_data = {"dreamplace": overrides}

    result = apply_parameter_overrides(dreamplace_default_config, parameter_data)

    assert result["routability_opt_flag"] == overrides["routability_opt_flag"]
    assert result["target_density"] == overrides["target_density"]


def test_nested_dreamplace_overrides_win_over_flat_keys(dreamplace_default_config):
    flat_value = _alternate_flag(dreamplace_default_config["routability_opt_flag"])
    nested_value = _alternate_flag(flat_value)
    parameter_data = {
        "routability_opt_flag": flat_value,
        "dreamplace": {"routability_opt_flag": nested_value},
    }

    result = apply_parameter_overrides(dreamplace_default_config, parameter_data)

    assert result["routability_opt_flag"] == nested_value


def test_non_dict_dreamplace_value_keeps_flat_mappings(dreamplace_default_config):
    flat_value = _alternate_flag(dreamplace_default_config["routability_opt_flag"])
    parameter_data = {
        "routability_opt_flag": flat_value,
        "dreamplace": "invalid",
    }

    result = apply_parameter_overrides(dreamplace_default_config, parameter_data)

    assert result["routability_opt_flag"] == flat_value


def test_apply_parameter_overrides_copies_inputs():
    base = {"nested": {"value": 1}}
    parameter_data = {"dreamplace": {"list_value": [1, 2, 3]}}

    result = apply_parameter_overrides(base, parameter_data)

    result["nested"]["value"] = 2
    result["list_value"].append(4)

    assert base == {"nested": {"value": 1}}
    assert parameter_data == {"dreamplace": {"list_value": [1, 2, 3]}}
