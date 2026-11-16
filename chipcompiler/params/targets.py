"""Derive managed tool-config fields from workspace parameters.

One pass writes every parameter that owns config targets into the workspace
``config/*.json`` files:

- a parameter stored in the workspace payload (``maps_to``) is rendered from
  that stored value;
- a ``fork`` parameter forks the PDK-effective default out to its targets.

Explicit user values for direct config parameters are not handled here: they
live in the ``config_overrides`` patch, which is replayed after this pass.
"""

from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from chipcompiler.data.config_params.common import ConfigTarget, ParamSchema
from chipcompiler.data.parameter_schema import list_schemas
from chipcompiler.data.workspace.config_overrides import config_path_for_key
from chipcompiler.utility import json_read_strict, json_write

_MISSING: object = object()


def _stored_value(parameters: Mapping[str, object], maps_to: str | dict[str, str]) -> object:
    if isinstance(maps_to, str):
        return parameters.get(maps_to, _MISSING)
    parent, child = next(iter(maps_to.items()))
    node = parameters.get(parent)
    return node.get(child, _MISSING) if isinstance(node, Mapping) else _MISSING


def _effective_value(schema: ParamSchema, parameters: Mapping[str, object]) -> object:
    if schema.maps_to is not None:
        return _stored_value(parameters, schema.maps_to)
    if schema.fork:
        return schema.default_for(str(parameters.get("pdk") or "") or None)
    return _MISSING


def _carries(target: ConfigTarget, value: object) -> bool:
    """Whether *value* has the element this target stores."""
    if target.element is None:
        return True
    return (
        isinstance(value, Sequence)
        and not isinstance(value, str | bytes)
        and len(value) > target.element
    )


def _set_nested(config: dict, path: tuple[str, ...], value: object) -> None:
    current = config
    for key in path[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    current[path[-1]] = value


def derive_parameter_configs(
    config_paths: Mapping[str, Path],
    parameters: Mapping[str, object],
    only: Collection[str] | None = None,
) -> None:
    """Write every stored or forked parameter into its config targets.

    *only* limits the pass to targets of the named config keys (case-insensitive),
    for step-level refreshes that must not touch the other managed configs.
    """
    selected = None if only is None else {key.casefold() for key in only}
    staged: dict[Path, dict] = {}
    for schema in list_schemas():
        if not schema.config_targets:
            continue
        value = _effective_value(schema, parameters)
        if value is _MISSING:
            continue
        for target in schema.config_targets:
            if not _carries(target, value):
                continue
            if selected is not None and target.config_key.casefold() not in selected:
                continue
            path = config_path_for_key(dict(config_paths), target.config_key)
            if path is None:
                raise ValueError(f"unknown config target: {target.config_key}")
            config = staged.get(path)
            if config is None:
                loaded = json_read_strict(path)
                if not isinstance(loaded, dict):
                    raise ValueError(f"workspace config must be an object: {path}")
                config = staged[path] = loaded
            _set_nested(config, target.json_path, target.render(value))
    for path, config in staged.items():
        if not json_write(path, config):
            raise OSError(f"Failed to write config: {path}")
