from copy import deepcopy

from chipcompiler.tools.ecc_dreamplace.parameter_overrides import (
    apply_parameter_overrides,
)


def _alternate_flag(value):
    return 0 if value else 1


def _alternate_float(value):
    return 0.65 if value != 0.65 else 0.7


def test_nested_dreamplace_overrides_are_applied(dreamplace_default_config):
    overrides = {
        "routability_opt_flag": _alternate_flag(dreamplace_default_config["routability_opt_flag"]),
        "target_density": _alternate_float(dreamplace_default_config["target_density"]),
    }
    parameter_data = {"dreamplace": overrides}

    result = apply_parameter_overrides(dreamplace_default_config, parameter_data)

    assert result["routability_opt_flag"] == overrides["routability_opt_flag"]
    assert result["target_density"] == overrides["target_density"]


def test_apply_parameter_overrides_copies_inputs():
    base = {"nested": {"value": 1}}
    parameter_data = {"dreamplace": {"list_value": [1, 2, 3]}}

    result = apply_parameter_overrides(base, parameter_data)

    result["nested"]["value"] = 2
    result["list_value"].append(4)

    assert base == {"nested": {"value": 1}}
    assert parameter_data == {"dreamplace": {"list_value": [1, 2, 3]}}


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
    parameter_data = {"dreamplace": overrides}
    assert save_workspace_config(tmp_path, parameter_data)

    loaded = load_parameter(tmp_path / "home" / "params.toml")
    expected = deepcopy(dreamplace_default_config)
    expected.update(overrides)

    assert apply_parameter_overrides(dreamplace_default_config, loaded.data) == expected


def test_direct_config_overrides_win_without_aliasing_inputs(dreamplace_default_config):
    stages = deepcopy(dreamplace_default_config["global_place_stages"])
    stages[0]["iteration"] = 12
    parameter_data = {
        "dreamplace": {"target_density": 0.55},
        "config_overrides": {
            "dreamplace": {"target_density": 0.75, "global_place_stages": stages},
            "routing": {"RT": {"-thread_number": 64}},
        },
    }
    original_parameters = deepcopy(parameter_data)
    expected = deepcopy(dreamplace_default_config)
    expected.update(target_density=0.75, global_place_stages=stages)

    result = apply_parameter_overrides(dreamplace_default_config, parameter_data)

    assert result == expected
    result["global_place_stages"][0]["iteration"] = 20
    assert parameter_data == original_parameters
