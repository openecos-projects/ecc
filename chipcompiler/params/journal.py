"""Workspace-local parameter edits, their baseline journal and rebuild carry-over."""

import os
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


def _pdk_relative_liberty(entries: object, pdk_root: str) -> object:
    """``sta.liberty`` entries with paths under *pdk_root* in their PDK-relative form."""
    root = pdk_root.rstrip(os.sep)
    if not root or not isinstance(entries, list):
        return entries
    rebound = deepcopy(entries)
    for entry in rebound:
        if isinstance(entry, dict) and isinstance(entry.get("path"), list):
            entry["path"] = [
                path[len(root) + 1 :]
                if isinstance(path, str) and path.startswith(f"{root}{os.sep}")
                else path
                for path in entry["path"]
            ]
    return rebound


def carried_parameters(parameters: Mapping[str, object], pdk_root: str = "") -> dict[str, object]:
    """The user-adjustable parameters a rebuilt Workspace inherits.

    Liberty paths that point inside *pdk_root* are carried PDK-relative, so a
    PDK migration re-resolves them against the new root instead of pinning the
    old one; paths outside the PDK (external macro libraries) are kept as given.

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
    _rebind_liberty(carried, pdk_root)
    return carried


def _rebind_liberty(carried: dict[str, object], pdk_root: str) -> None:
    patch = carried.get(CONFIG_OVERRIDES_KEY)
    sta = patch.get("sta") if isinstance(patch, dict) else None
    if isinstance(sta, dict) and "liberty" in sta:
        sta["liberty"] = _pdk_relative_liberty(sta["liberty"], pdk_root)
    records = carried.get(WORKSPACE_PARAM_OVERRIDES_KEY)
    for record in records if isinstance(records, list) else []:
        if isinstance(record, dict) and record.get("key") == "sta.liberty":
            for field in ("value", "baseline"):
                if field in record:
                    record[field] = _pdk_relative_liberty(record[field], pdk_root)


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
