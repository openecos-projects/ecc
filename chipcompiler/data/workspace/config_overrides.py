"""Replay validated direct tool-configuration overrides into workspace JSON files."""

from pathlib import Path

from chipcompiler.utility import json_read, json_write

CONFIG_OVERRIDES_KEY = "config_overrides"
_LEGACY_CONFIG_OVERRIDES_KEY = "Config Overrides"


def apply_config_overrides(config_paths: dict[str, Path], parameters: dict) -> None:
    overrides = parameters.get(CONFIG_OVERRIDES_KEY)
    if overrides is None:
        overrides = parameters.get(_LEGACY_CONFIG_OVERRIDES_KEY)
    if not isinstance(overrides, dict):
        return

    for config_key, patch in overrides.items():
        config_path = _config_path_for_key(config_paths, config_key)
        if config_path is None:
            raise ValueError(f"unknown config override target: {config_key}")
        if not isinstance(patch, dict):
            raise ValueError(f"config override patch must be an object: {config_key}")
        config = json_read(config_path)
        _merge_config_patch(config, patch)
        if not json_write(config_path, config):
            raise OSError(f"Failed to write config override: {config_path}")


def _config_path_for_key(config_paths: dict[str, Path], config_key: object) -> Path | None:
    if not isinstance(config_key, str) or config_key.casefold() == "dir":
        return None
    exact = config_paths.get(config_key)
    if exact is not None:
        return exact
    key = config_key.casefold()
    matches = [
        path
        for candidate, path in config_paths.items()
        if candidate != "dir" and candidate.casefold() == key
    ]
    return matches[0] if len(matches) == 1 else None


def _merge_config_patch(config: dict, patch: dict) -> None:
    for key, value in patch.items():
        existing = config.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            _merge_config_patch(existing, value)
        else:
            config[key] = value
