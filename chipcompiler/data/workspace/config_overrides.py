"""Replay validated direct tool-configuration overrides into workspace JSON files.

Overrides are validated and staged against strict reads of the current
configurations, then committed atomically per file (sibling temp +
replace) with rollback of already-written files if a later commit fails,
so a partial override set can never replace a real tool configuration.
"""

import json
import os
import tempfile
from pathlib import Path

CONFIG_OVERRIDES_KEY = "config_overrides"
_LEGACY_CONFIG_OVERRIDES_KEY = "Config Overrides"


def apply_config_overrides(config_paths: dict[str, Path], parameters: dict) -> None:
    overrides = parameters.get(CONFIG_OVERRIDES_KEY)
    if overrides is None:
        overrides = parameters.get(_LEGACY_CONFIG_OVERRIDES_KEY)
    if not isinstance(overrides, dict):
        return

    staged: list[tuple[Path, dict, bytes | None]] = []
    for config_key, patch in overrides.items():
        config_path = _config_path_for_key(config_paths, config_key)
        if config_path is None:
            raise ValueError(f"unknown config override target: {config_key}")
        if not isinstance(patch, dict):
            raise ValueError(f"config override patch must be an object: {config_key}")
        # Strict read: json_read's tolerant {} fallback would replace a real
        # tool configuration with only the patch on a corrupt or missing
        # file. An unreadable target must abort the whole override set.
        config = _read_json_strict(config_path)
        _merge_config_patch(config, patch)
        original = config_path.read_bytes() if config_path.is_file() else None
        staged.append((config_path, config, original))

    written: list[tuple[Path, bytes | None]] = []
    try:
        for config_path, config, original in staged:
            _write_json_strict(config_path, config)
            written.append((config_path, original))
    except OSError:
        for config_path, original in reversed(written):
            if original is None:
                config_path.unlink(missing_ok=True)
            else:
                config_path.write_bytes(original)
        raise


def _read_json_strict(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError as exc:
        raise ValueError(f"config override target does not exist: {path}") from exc
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"config override target is unreadable or corrupt: {path}: {exc}") from exc
    if not isinstance(data, dict):
        # A valid JSON scalar/array is not a tool configuration: overwriting
        # it with only the patch would be destructive data loss.
        raise ValueError(f"config override target must be a JSON object: {path}")
    return data


def _write_json_strict(path: Path, config: dict) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(config, file, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        os.unlink(tmp_path)
        raise


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
