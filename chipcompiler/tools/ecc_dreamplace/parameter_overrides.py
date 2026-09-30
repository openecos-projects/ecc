#!/usr/bin/env python

from copy import deepcopy

from chipcompiler.data.parameter import update_parameters

DREAMPLACE_PARAMETER_KEYS = {
    "target_density": "target_density",
    "target_overflow": "stop_overflow",
    "cell_padding_x": "cell_padding_x",
    "routability_opt_flag": "routability_opt_flag",
    "bottom_layer": "gpugr_bottom_routing_layer",
    "top_layer": "gpugr_top_routing_layer",
}


def apply_parameter_overrides(
    base_params: dict,
    parameter_data: dict,
) -> dict:
    """Apply workspace parameter overrides to a copied DreamPlace config."""
    params = deepcopy(base_params)

    for parameter_key, dreamplace_key in DREAMPLACE_PARAMETER_KEYS.items():
        if parameter_key in parameter_data:
            params[dreamplace_key] = deepcopy(parameter_data[parameter_key])

    dreamplace_overrides = parameter_data.get("dreamplace", {})
    if isinstance(dreamplace_overrides, dict):
        for key, value in dreamplace_overrides.items():
            params[key] = deepcopy(value)

    # Step builders reapply workspace parameters, so direct CLI patches must stay last.
    config_overrides = parameter_data.get("config_overrides", {})
    if isinstance(config_overrides, dict):
        for config_key, direct_overrides in config_overrides.items():
            if config_key.casefold() == "dreamplace" and isinstance(direct_overrides, dict):
                update_parameters(deepcopy(direct_overrides), params)

    return params
