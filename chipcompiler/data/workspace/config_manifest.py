#!/usr/bin/env python

"""Last-derived-state record for the generated ``config/*.json`` files.

``refresh_workspace_config`` regenerates the parameter/PDK-derived fields
of the managed workspace configs. ``ecc workspace refresh`` overwrites those
files wholesale from ``ecc.toml``; comparing the on-disk content against
this record distinguishes a file touched since the last derivation (a hand
edit, or any write outside the derivation path) from an untouched tree, so
refresh can refuse to clobber edits instead of silently discarding them.
"""

from pathlib import Path

from chipcompiler.utility import file_digest, json_read, json_write

DERIVED_CONFIG_MANIFEST_FILENAME = "config-derived-manifest.json"


def derived_config_manifest_path(workspace_dir: str | Path) -> Path:
    return Path(workspace_dir) / "home" / DERIVED_CONFIG_MANIFEST_FILENAME


def record_derived_config(workspace) -> bool:
    """Write the hash manifest of the managed config files after a derivation.

    Called at the end of ``refresh_workspace_config`` (atomic tmp+replace,
    the same transaction style as the other ``home/`` JSON state), so the
    record always describes exactly what the derivation produced.
    """
    from . import _WORKSPACE_CONFIG_FILENAMES

    if not workspace.config:
        return False
    config_dir_value = workspace.config.get("dir")
    if config_dir_value is None or workspace.directory is None:
        return False
    config_dir = Path(config_dir_value)
    if not config_dir.is_dir():
        return False
    files = {}
    for filename in sorted(set(_WORKSPACE_CONFIG_FILENAMES.values())):
        digest = file_digest(config_dir / filename)
        if digest is not None:
            files[filename] = {"sha256": digest[0], "size": digest[1]}
    manifest_path = derived_config_manifest_path(workspace.directory)
    # init_workspace_config runs before home/ exists (create_workspace makes
    # it later), so the atomic json_write needs the parent prepared.
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    return json_write(manifest_path, {"files": files})


def modified_derived_configs(workspace_dir: str | Path) -> list[str]:
    """Managed config files whose content differs from the last derivation.

    An absent or empty record (first refresh, or a workspace predating the
    record) means there is nothing to compare against: refresh proceeds.
    """
    manifest = json_read(derived_config_manifest_path(workspace_dir))
    recorded = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(recorded, dict) or not recorded:
        return []
    config_dir = Path(workspace_dir) / "config"
    modified = []
    for filename in sorted(recorded):
        digest = file_digest(config_dir / filename)
        current = {"sha256": digest[0], "size": digest[1]} if digest is not None else None
        if current != recorded[filename]:
            modified.append(filename)
    return modified
