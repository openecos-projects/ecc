#!/usr/bin/env python

from __future__ import annotations

from copy import deepcopy

LEGACY_DREAMPLACE_PARAMETER_KEYS = {
    "Target density": "target_density",
    "Target overflow": "stop_overflow",
    "Cell padding x": "cell_padding_x",
    "Routability opt flag": "routability_opt_flag",
}


def apply_parameter_overrides(
    base_params: dict,
    parameter_data: dict,
) -> dict:
    """Apply workspace parameter overrides to a copied DreamPlace config."""
    params = deepcopy(base_params)

    for parameter_key, dreamplace_key in LEGACY_DREAMPLACE_PARAMETER_KEYS.items():
        if parameter_key in parameter_data:
            params[dreamplace_key] = deepcopy(parameter_data[parameter_key])

    dreamplace_overrides = parameter_data.get("DreamPlace", {})
    if isinstance(dreamplace_overrides, dict):
        for key, value in dreamplace_overrides.items():
            params[key] = deepcopy(value)

    return params
