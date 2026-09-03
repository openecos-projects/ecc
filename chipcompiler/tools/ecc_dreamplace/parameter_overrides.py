#!/usr/bin/env python

from copy import deepcopy

DREAMPLACE_PARAMETER_KEYS = {
    "target_density": "target_density",
    "target_overflow": "stop_overflow",
    "cell_padding_x": "cell_padding_x",
    "routability_opt_flag": "routability_opt_flag",
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

    return params
