"""Workspace-local parameter persistence shared by Engine and CLI."""

from copy import deepcopy
from typing import Final

from chipcompiler.data.config_params.common import ConfigTarget
from chipcompiler.data.parameter import update_parameters
from chipcompiler.data.parameter_schema import (
    ResolvedParam,
    build_backend_overrides,
    build_config_overrides,
)
from chipcompiler.data.types import SkippableStepEnum, StepEnum
from chipcompiler.data.workspace.config_overrides import CONFIG_OVERRIDES_KEY
from chipcompiler.utility import json_read

WORKSPACE_PARAM_OVERRIDES_KEY = "workspace_param_overrides"
# Layer (``ecc.toml`` / ``cli``) that supplied each explicit parameter at creation.
PARAM_SOURCES_KEY = "_param_sources"
# Steps a parameter's ``applies`` may name and still be set on an existing workspace.
_SETTABLE_APPLIES: Final = frozenset(
    {
        StepEnum.SYNTHESIS.value,
        StepEnum.FLOORPLAN.value,
        StepEnum.PLACEMENT.value,
        StepEnum.MACRO_PLACEMENT.value,
        StepEnum.CTS.value,
        StepEnum.ROUTING.value,
        StepEnum.FILLER.value,
        StepEnum.RCX.value,
        StepEnum.STA.value,
        StepEnum.EMIR.value,
        SkippableStepEnum.TIMING_OPT.value,
        SkippableStepEnum.DIFF_OPT.value,
        StepEnum.DIFF_SIZING.value,
    }
)
_MISSING = object()


def workspace_param_step(schema, workspace=None) -> str | None:
    """The earliest flow step a parameter change invalidates.

    ``applies`` may name several steps (``"placement,diff_opt"``) or ``"all"``;
    both resolve against the Workspace's flow when one is given.
    """
    if schema.output_only:
        return None
    # Only multi-step and "all" parameters need the flow to pick their step.
    flow_names: list[str] = []
    if workspace is not None and ("," in schema.applies or schema.applies == "all"):
        flow_names = [str(step.get("name", "")) for step in workspace.flow.steps()]
    candidates: list[str] = []
    for applies in (part.strip() for part in schema.applies.split(",")):
        if applies == "all":
            # Without a Workspace the caller only asks whether the parameter is settable.
            candidates.extend(flow_names[:1] or ["all"])
        elif applies in _SETTABLE_APPLIES:
            candidates.append(applies)
    if not candidates:
        raise ValueError(f"{schema.param} requires a full workspace refresh")
    return next((name for name in flow_names if name in candidates), candidates[0])


def workspace_param_value(workspace, schema, *, strict: bool = False) -> object:
    if schema.pdk_target is not None:
        raise ValueError(f"{schema.param} requires a full workspace refresh")
    pdk = str(workspace.parameters.data.get("pdk") or "") or None
    default = schema.default_for(pdk)
    if schema.maps_to is not None:
        return _parameter_target_value(workspace.parameters.data, schema.maps_to, default)
    if schema.config_target is not None:
        return _config_target_value(workspace, schema, default, strict=strict)
    raise ValueError(f"{schema.param} has no workspace configuration target")


def _read_target(workspace, target: ConfigTarget, *, strict: bool) -> object:
    """The parameter-side value stored at *target*, or ``_MISSING``."""
    config_path = workspace.config.get(target.config_key)
    if config_path is None:
        raise ValueError(f"workspace config missing target: {target.config_key}")
    if strict:
        from chipcompiler.utility import json_read_strict

        config = json_read_strict(config_path)
        if not isinstance(config, dict):
            raise ValueError(f"workspace config must be an object: {config_path}")
    else:
        config = json_read(config_path)
    value = _nested_value(config, target.json_path)
    return value if value is _MISSING else target.parse(value)


def _config_target_value(workspace, schema, default: object, *, strict: bool) -> object:
    targets = schema.config_targets
    if all(target.element is None for target in targets):
        value = _read_target(workspace, targets[0], strict=strict)
        return default if value is _MISSING else value
    # A list parameter fanned out per element: read each element from its
    # first target; any missing element falls back to the default list.
    size = 1 + max(target.element for target in targets if target.element is not None)
    elements: list[object] = []
    for index in range(size):
        target = next((item for item in targets if item.element == index), None)
        value = _MISSING if target is None else _read_target(workspace, target, strict=strict)
        if value is _MISSING:
            return default
        elements.append(value)
    return elements


def set_workspace_param(workspace, schema, value: object) -> tuple[object, str | None]:
    baseline = update_workspace_param_value(workspace, schema, value)
    return baseline, workspace_param_step(schema, workspace)


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


def unset_workspace_param(workspace, schema) -> tuple[object, str | None] | None:
    records = _override_records(workspace.parameters.data)
    record = next((item for item in records if item["key"] == schema.param), None)
    if record is None:
        return None
    records.remove(record)
    _set_override_records(workspace.parameters.data, records)
    _apply_workspace_value(workspace, schema, record["baseline"])
    return record["baseline"], workspace_param_step(schema, workspace)


def workspace_param_diff(workspace) -> list[dict]:
    return _override_records(workspace.parameters.data)


def _apply_workspace_value(workspace, schema, value: object) -> None:
    resolved = ResolvedParam(schema.param, value, schema.default, "workspace", schema)
    update_parameters(build_backend_overrides([resolved]), workspace.parameters.data)
    config_overrides = build_config_overrides([resolved])
    if config_overrides:
        update_parameters({CONFIG_OVERRIDES_KEY: config_overrides}, workspace.parameters.data)
    if schema.output_only:
        from chipcompiler.data.workspace.flow_options import sync_flow_options_projection

        sync_flow_options_projection(workspace)


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
