"""Replay validated direct tool-configuration overrides into workspace JSON files."""

from pathlib import Path

from chipcompiler.utility import json_read, json_write

CONFIG_OVERRIDES_KEY = "Config Overrides"


def apply_config_overrides(config_paths: dict[str, Path], parameters: dict) -> None:
    overrides = parameters.get(CONFIG_OVERRIDES_KEY)
    if not isinstance(overrides, dict):
        return

    for config_key, patch in overrides.items():
        config_path = config_paths.get(config_key)
        if config_key == "dir" or config_path is None or not isinstance(patch, dict):
            continue
        config = json_read(config_path)
        _merge_config_patch(config, patch)
        if not json_write(config_path, config):
            raise OSError(f"Failed to write config override: {config_path}")


def _merge_config_patch(config: dict, patch: dict) -> None:
    for key, value in patch.items():
        existing = config.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            _merge_config_patch(existing, value)
        else:
            config[key] = value
