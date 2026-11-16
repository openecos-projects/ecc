#!/usr/bin/env python

from copy import deepcopy

from chipcompiler.data.parameter import update_parameters


def apply_parameter_overrides(
    base_params: dict,
    parameter_data: dict,
) -> dict:
    """Apply workspace parameter overrides to a copied DreamPlace config."""
    params = deepcopy(base_params)

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


def apply_direct_config_overrides(params: dict, parameter_data: dict) -> dict:
    """Reapply the direct DreamPlace JSON patch after flow-profile expansion."""
    result = deepcopy(params)
    overrides = parameter_data.get("config_overrides")
    if not isinstance(overrides, dict):
        return result

    patch = next(
        (
            value
            for key, value in overrides.items()
            if isinstance(key, str)
            and key.casefold() in {"dreamplace", "dreamplace.json", "dreamplace_ecc.json"}
        ),
        None,
    )
    if not isinstance(patch, dict):
        return result

    def merge(target: dict, source: dict) -> None:
        for key, value in source.items():
            if isinstance(target.get(key), dict) and isinstance(value, dict):
                merge(target[key], value)
            else:
                target[key] = deepcopy(value)

    merge(result, patch)
    return result
