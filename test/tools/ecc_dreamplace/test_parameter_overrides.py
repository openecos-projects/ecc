from copy import deepcopy

import pytest

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


@pytest.mark.parametrize(
    "dreamplace_overrides",
    [{}, {"gpugr_bottom_routing_layer": "M3", "gpugr_top_routing_layer": "M4"}],
)
def test_gpugr_layers_follow_workspace_unless_explicitly_overridden(
    dreamplace_default_config, dreamplace_overrides
):
    parameter_data = {
        "bottom_layer": "M2",
        "top_layer": "M5",
        "dreamplace": dreamplace_overrides,
    }
    expected = deepcopy(dreamplace_default_config)
    expected.update(gpugr_bottom_routing_layer="M2", gpugr_top_routing_layer="M5")
    expected.update(dreamplace_overrides)

    assert apply_parameter_overrides(dreamplace_default_config, parameter_data) == expected


def test_routability_options_survive_workspace_toml_loading(tmp_path, dreamplace_default_config):
    from chipcompiler.data.parameter import load_parameter
    from chipcompiler.data.workspace_config import save_workspace_config

    overrides = {
        "l_shape_routability_flag": 1,
        "l_shape_update_interval": 30,
        "gpugr_backend": "cpu_pr_mt",
        "gpugr_area_adjust_rrr_iters": 0,
        "max_num_area_adjust": 5,
    }
    parameter_data = {"bottom_layer": "M2", "top_layer": "M5", "dreamplace": overrides}
    assert save_workspace_config(tmp_path, parameter_data)

    loaded = load_parameter(tmp_path / "home" / "params.toml")
    expected = deepcopy(dreamplace_default_config)
    expected.update(gpugr_bottom_routing_layer="M2", gpugr_top_routing_layer="M5")
    expected.update(overrides)

    assert apply_parameter_overrides(dreamplace_default_config, loaded.data) == expected


def test_direct_config_overrides_win_without_aliasing_inputs(dreamplace_default_config):
    stages = deepcopy(dreamplace_default_config["global_place_stages"])
    stages[0]["iteration"] = 12
    parameter_data = {
        "target_density": 0.65,
        "dreamplace": {"target_density": 0.55},
        "config_overrides": {
            "dreamplace": {"target_density": 0.75, "global_place_stages": stages},
            "route": {"RT": {"-thread_number": 64}},
        },
    }
    original_parameters = deepcopy(parameter_data)
    expected = deepcopy(dreamplace_default_config)
    expected.update(target_density=0.75, global_place_stages=stages)

    result = apply_parameter_overrides(dreamplace_default_config, parameter_data)

    assert result == expected
    result["global_place_stages"][0]["iteration"] = 20
    assert parameter_data == original_parameters
