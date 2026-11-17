"""Workspace-local parameter persistence shared by Engine and CLI."""

from copy import deepcopy

from chipcompiler.data.config_params.common import WORKSPACE_WIDE, ConfigTarget
from chipcompiler.data.parameter import update_parameters
from chipcompiler.data.parameter_schema import (
    ResolvedParam,
    build_backend_overrides,
    build_config_overrides,
)
from chipcompiler.data.step_parameters import (
    ParameterStepError,
    check_parameter_step,
    is_step_scoped,
    set_step_value,
    step_value,
    unset_step_value,
)
from chipcompiler.data.workspace import step_config_keys
from chipcompiler.data.workspace.config_overrides import CONFIG_OVERRIDES_KEY
from chipcompiler.utility import json_read

WORKSPACE_PARAM_OVERRIDES_KEY = "workspace_param_overrides"
# Layer (``ecc.toml`` / ``cli``) that supplied each explicit parameter at creation.
PARAM_SOURCES_KEY = "_param_sources"
_MISSING = object()


def workspace_param_step(schema, workspace=None, step: str | None = None) -> str | None:
    """The earliest flow step a parameter change invalidates.

    A step-scoped parameter invalidates the *step* whose value changed. Any
    other parameter invalidates from the earliest flow step that either is
    one of its declared steps or reads one of its target configs
    (:func:`~chipcompiler.data.workspace.step_config_keys`): a routing layer
    also written into the floorplan ``db`` config invalidates the floorplan.
    A workspace-wide parameter invalidates the Workspace's first step.
    Without a Workspace the declared order decides (``"all"`` for a
    workspace-wide parameter).
    """
    if schema.output_only:
        return None
    if schema.pdk_target is not None:
        raise ValueError(f"{schema.param} requires a full workspace refresh")
    if is_step_scoped(schema) and step is not None:
        return check_parameter_step(schema, step)
    flow = _flow_steps(workspace)
    if schema.workspace_wide:
        return flow[0][0] if flow else WORKSPACE_WIDE
    targets = (
        set()
        if is_step_scoped(schema)
        else {target.config_key.casefold() for target in schema.config_targets}
    )
    for name, tool in flow:
        reads = {key.casefold() for key in step_config_keys(name, tool)}
        if schema.applies_to(name) or targets & reads:
            return name
    return schema.steps[0]


def _flow_steps(workspace) -> list[tuple[str, str | None]]:
    """``(name, tool)`` of each step of *workspace*'s flow, in order."""
    if workspace is None:
        return []
    # ``load_workspace`` keeps the flow ledger lazy; the accessor hydrates it.
    accessor = getattr(workspace.flow, "steps", None)
    steps = accessor() if callable(accessor) else workspace.flow.data.get("steps", [])
    return [
        (str(item.get("name", "")), item.get("tool"))
        for item in steps
        if isinstance(item, dict) and item.get("name")
    ]


def workspace_param_value(
    workspace, schema, *, step: str | None = None, strict: bool = False
) -> object:
    """The value *schema* holds in *workspace* (at *step* for a step-scoped parameter).

    A step-scoped parameter reads the step's stored value, else the value
    the workspace baseline config carries; generated step configs are never
    read, since they are stale until the step runs again.
    """
    if schema.pdk_target is not None:
        raise ValueError(f"{schema.param} requires a full workspace refresh")
    if step is not None and is_step_scoped(schema):
        stored = step_value(workspace.parameters.data, step, schema.param, _MISSING)
        if stored is not _MISSING:
            return stored
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


def set_workspace_param(
    workspace, schema, value: object, step: str | None = None
) -> tuple[object, str | None]:
    baseline = update_workspace_param_value(workspace, schema, value, step=step)
    return baseline, workspace_param_step(schema, workspace, _scope(schema, step))


def update_workspace_param_value(
    workspace, schema, value: object, *, step: str | None = None
) -> object:
    """Journal and apply *value*; a step-scoped parameter needs its *step*.

    Raises :class:`~chipcompiler.data.step_parameters.ParameterStepError`
    for a missing or inapplicable step.
    """
    scope = _checked_scope(workspace, schema, step)
    records = _override_records(workspace.parameters.data)
    record = _find_record(records, schema.param, scope)
    if record is None:
        record = {
            "key": schema.param,
            "baseline": deepcopy(workspace_param_value(workspace, schema, step=scope)),
        }
        if scope is not None:
            record["step"] = scope
            # Unset removes the step value again unless the step already had one.
            record["stored"] = (
                step_value(workspace.parameters.data, scope, schema.param, _MISSING) is not _MISSING
            )
        records.append(record)
    record["value"] = deepcopy(value)
    _set_override_records(workspace.parameters.data, records)
    _apply_workspace_value(workspace, schema, value, scope)
    return record["baseline"]


def unset_workspace_param(
    workspace, schema, step: str | None = None
) -> tuple[object, str | None] | None:
    scope = _checked_scope(workspace, schema, step)
    records = _override_records(workspace.parameters.data)
    record = _find_record(records, schema.param, scope)
    if record is None:
        return None
    records.remove(record)
    _set_override_records(workspace.parameters.data, records)
    if scope is not None and not record.get("stored", True):
        unset_step_value(workspace.parameters.data, scope, schema.param)
    else:
        _apply_workspace_value(workspace, schema, record["baseline"], scope)
    return record["baseline"], workspace_param_step(schema, workspace, scope)


def _checked_scope(workspace, schema, step: str | None) -> str | None:
    """The validated journal scope of an edit; a step value's step must be in the flow."""
    scope = check_parameter_step(schema, _scope(schema, step))
    if scope is not None and scope not in {name for name, _tool in _flow_steps(workspace)}:
        raise ParameterStepError(
            "unknown_flow_step",
            schema.param,
            scope,
            f"step {scope} is not in this workspace's flow",
        )
    return scope


def _scope(schema, step: str | None) -> str | None:
    """The journal scope of an edit: its step for a step-scoped parameter, else none."""
    return step if is_step_scoped(schema) else None


def _find_record(records: list[dict], param: str, step: str | None) -> dict | None:
    return next(
        (item for item in records if item["key"] == param and item.get("step") == step), None
    )


def workspace_param_diff(workspace) -> list[dict]:
    return _override_records(workspace.parameters.data)


def _apply_workspace_value(workspace, schema, value: object, step: str | None = None) -> None:
    if step is not None:
        set_step_value(workspace.parameters.data, step, schema.param, value)
        return
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
