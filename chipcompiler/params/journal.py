"""Workspace-local parameter edits, their baseline journal and rebuild carry-over."""

from collections.abc import Mapping
from copy import deepcopy

from chipcompiler.data.parameter_schema import list_schemas, lookup_schema, validate_value
from chipcompiler.data.workspace.config_overrides import CONFIG_OVERRIDES_KEY
from chipcompiler.data.workspace_parameters import (
    PARAM_SOURCES_KEY,
    WORKSPACE_PARAM_OVERRIDES_KEY,
    set_workspace_param,
    unset_workspace_param,
    update_workspace_param_value,
    workspace_param_diff,
    workspace_param_step,
    workspace_param_value,
)

from .targets import MISSING, stored_value

__all__ = [
    "PARAM_SOURCES_KEY",
    "WORKSPACE_PARAM_OVERRIDES_KEY",
    "carried_parameters",
    "invalid_carried_parameters",
    "set_workspace_param",
    "unset_workspace_param",
    "update_workspace_param_value",
    "workspace_param_diff",
    "workspace_param_step",
    "workspace_param_value",
]


def carried_parameters(parameters: Mapping[str, object]) -> dict[str, object]:
    """The user-adjustable parameters a rebuilt Workspace inherits.

    Structural keys (design, PDK, flow, inputs) come from the new Workspace
    Spec; runtime results (die/core geometry) are regenerated. What survives is
    every stored tunable (``maps_to`` parameters), the direct config patch and
    the baseline journal.
    """
    carried: dict[str, object] = {}
    for schema in list_schemas():
        if schema.maps_to is None:
            continue
        value = stored_value(parameters, schema.maps_to)
        if value is MISSING:
            continue
        if isinstance(schema.maps_to, str):
            carried[schema.maps_to] = deepcopy(value)
        else:
            parent, child = next(iter(schema.maps_to.items()))
            nested = carried.setdefault(parent, {})
            if isinstance(nested, dict):
                nested[child] = deepcopy(value)
    for key in (CONFIG_OVERRIDES_KEY, WORKSPACE_PARAM_OVERRIDES_KEY, PARAM_SOURCES_KEY):
        if key in parameters:
            carried[key] = deepcopy(parameters[key])
    return carried


def invalid_carried_parameters(carried: Mapping[str, object], pdk: str | None) -> list[str]:
    """Range and choice errors of carried values under the new PDK family.

    Covers the journaled workspace edits and the direct config patch, which also
    holds the values given at creation through ``ecc.toml`` or ``--set``.
    """
    errors: list[str] = []
    records = carried.get(WORKSPACE_PARAM_OVERRIDES_KEY)
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict) or "value" not in record:
            continue
        schema = lookup_schema(str(record.get("key", "")))
        if schema is not None and schema.pdk_target is None:
            errors.extend(validate_value(record["value"], schema, pdk))
    patch = carried.get(CONFIG_OVERRIDES_KEY)
    if isinstance(patch, Mapping):
        for schema in list_schemas():
            target = schema.config_target
            if target is None or schema.maps_to is not None or target.element is not None:
                continue
            node: object = patch.get(target.config_key)
            for key in target.json_path:
                node = node.get(key, MISSING) if isinstance(node, Mapping) else MISSING
            if node is not MISSING:
                errors.extend(validate_value(target.parse(node), schema, pdk))
    return errors
