"""Workspace-local parameter persistence shared by Engine and CLI."""

from copy import deepcopy

from chipcompiler.data.parameter import update_parameters
from chipcompiler.data.parameter_schema import (
    ResolvedParam,
    build_backend_overrides,
    build_config_overrides,
)
from chipcompiler.data.workspace.config_overrides import CONFIG_OVERRIDES_KEY
from chipcompiler.utility import json_read

WORKSPACE_PARAM_OVERRIDES_KEY = "workspace_param_overrides"
_APPLIES_TO_STEP = {
    "synthesis": "Synthesis",
    "floorplan": "Floorplan",
    "placement": "place",
    "cts": "CTS",
    "routing": "route",
    "filler": "filler",
    "rcx": "RCX",
    "sta": "sta",
}
_MISSING = object()


def workspace_param_step(schema) -> str:
    step = _APPLIES_TO_STEP.get(schema.applies)
    if step is None:
        raise ValueError(f"{schema.param} requires a full workspace refresh")
    return step


def workspace_param_value(workspace, schema) -> object:
    if schema.pdk_target is not None:
        raise ValueError(f"{schema.param} requires a full workspace refresh")
    if schema.maps_to is not None:
        return _parameter_target_value(workspace.parameters.data, schema.maps_to, schema.default)
    if schema.config_target is not None:
        config_path = workspace.config.get(schema.config_target.config_key)
        if config_path is None:
            raise ValueError(f"workspace config missing target: {schema.config_target.config_key}")
        value = _nested_value(json_read(config_path), schema.config_target.json_path)
        return schema.default if value is _MISSING else value
    raise ValueError(f"{schema.param} has no workspace configuration target")


def set_workspace_param(workspace, schema, value: object) -> tuple[object, str]:
    baseline = update_workspace_param_value(workspace, schema, value)
    return baseline, workspace_param_step(schema)


def update_workspace_param_value(workspace, schema, value: object) -> object:
    records = _override_records(workspace.parameters.data)
    record = next((item for item in records if item["key"] == schema.param), None)
    if record is None:
        record = {
            "key": schema.param,
            "baseline": deepcopy(workspace_param_value(workspace, schema)),
        }
        records.append(record)
    record["value"] = deepcopy(value)
    _set_override_records(workspace.parameters.data, records)
    _apply_workspace_value(workspace, schema, value)
    return record["baseline"]


def unset_workspace_param(workspace, schema) -> tuple[object, str] | None:
    records = _override_records(workspace.parameters.data)
    record = next((item for item in records if item["key"] == schema.param), None)
    if record is None:
        return None
    records.remove(record)
    _set_override_records(workspace.parameters.data, records)
    _apply_workspace_value(workspace, schema, record["baseline"])
    return record["baseline"], workspace_param_step(schema)


def workspace_param_diff(workspace) -> list[dict]:
    return _override_records(workspace.parameters.data)


def _apply_workspace_value(workspace, schema, value: object) -> None:
    resolved = ResolvedParam(schema.param, value, schema.default, "workspace", schema)
    update_parameters(build_backend_overrides([resolved]), workspace.parameters.data)
    config_overrides = build_config_overrides([resolved])
    if config_overrides:
        update_parameters({CONFIG_OVERRIDES_KEY: config_overrides}, workspace.parameters.data)


def _override_records(parameters: dict) -> list[dict]:
    raw = parameters.get(WORKSPACE_PARAM_OVERRIDES_KEY, [])
    if not isinstance(raw, list):
        return []
    return [
        deepcopy(item)
        for item in raw
        if isinstance(item, dict) and isinstance(item.get("key"), str) and "baseline" in item
    ]


def _set_override_records(parameters: dict, records: list[dict]) -> None:
    if records:
        parameters[WORKSPACE_PARAM_OVERRIDES_KEY] = records
    else:
        parameters.pop(WORKSPACE_PARAM_OVERRIDES_KEY, None)


def _parameter_target_value(parameters: dict, target, default: object) -> object:
    if isinstance(target, str):
        return deepcopy(parameters.get(target, default))
    if isinstance(target, dict) and len(target) == 1:
        parent, child = next(iter(target.items()))
        nested = parameters.get(parent)
        if isinstance(nested, dict):
            return deepcopy(nested.get(child, default))
    return deepcopy(default)


def _nested_value(data: object, path: tuple[str, ...]) -> object:
    current = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return _MISSING
        current = current[key]
    return deepcopy(current)
