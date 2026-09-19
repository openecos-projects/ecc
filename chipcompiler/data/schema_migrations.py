#!/usr/bin/env python

"""Central schema-version registry for workspace persistent files.

Three kinds of files under ``home/`` are versioned:

- ``params.toml`` — current version 1; a file without the field is version 0
  (the pre-versioning era) and loads through the legacy migration.
- ``flow.json`` — current version 1; version 0 when the field is absent.
- ``engineering-snapshot.json`` — versions 2 (production) and 3 (prepared);
  its field is spelled ``schemaVersion`` because the contract predates this
  registry and is shared with the GUI. The v2→v3 migration stays an explicit
  write-only seam; loading reads both versions natively, so it is registered
  for discovery rather than applied by the load chain.

The ad-hoc migrations that used to live at their call sites register here:
``{file type: {target version: migration}}``. A migration takes the workspace
directory and produces the registered version; loading applies the chain in
ascending order from the file's current version. A file that declares a
version newer than anything supported is rejected with its path and version —
never parsed silently.
"""

import json
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

SCHEMA_VERSION_FIELD = "schema_version"
SNAPSHOT_SCHEMA_VERSION_FIELD = "schemaVersion"

PARAMS_TOML = "params.toml"
FLOW_JSON = "flow.json"
ENGINEERING_SNAPSHOT = "engineering-snapshot.json"
WORKSPACE_CONFIGS = "workspace-configs"

#: Newest schema version each file type supports. Types without an entry
#: derive it from their registered migrations.
SUPPORTED_SCHEMA_VERSIONS: dict[str, int] = {
    PARAMS_TOML: 1,
    FLOW_JSON: 1,
    ENGINEERING_SNAPSHOT: 3,
}


class UnsupportedSchemaVersionError(ValueError):
    """A persistent file declares a schema_version newer than this ECC supports."""

    def __init__(self, path: Path | str, version: int, supported: int):
        super().__init__(
            f"unsupported schema_version {version} in {path} "
            f"(this ECC supports up to {supported}); upgrade ECC or restore the file"
        )
        self.path = Path(path)
        self.version = version
        self.supported = supported


def _migrate_params_toml_to_v1(workspace_dir: Path) -> None:
    from .workspace_config import migrate_legacy_parameters

    migrate_legacy_parameters(workspace_dir)


def _migrate_workspace_config_filenames_to_v1(workspace_dir: Path) -> None:
    from .workspace import migrate_workspace_config_filenames

    migrate_workspace_config_filenames(workspace_dir)


def _migrate_engineering_snapshot_to_v3(workspace_dir: Path) -> None:
    # The v2→v3 seam regenerates QoR facts and therefore needs the loaded
    # workspace, not just the directory; it stays an explicit operation.
    from chipcompiler.data import load_workspace
    from chipcompiler.engine import migrate_engineering_snapshot_v2_to_v3

    migrate_engineering_snapshot_v2_to_v3(load_workspace(workspace_dir))


#: {file type: {target version: migration producing that version}}.
SCHEMA_MIGRATIONS: dict[str, dict[int, Callable[[Path], None]]] = {
    PARAMS_TOML: {1: _migrate_params_toml_to_v1},
    WORKSPACE_CONFIGS: {1: _migrate_workspace_config_filenames_to_v1},
    ENGINEERING_SNAPSHOT: {3: _migrate_engineering_snapshot_to_v3},
}


def document_schema_version(document: object, file_type: str) -> int:
    """The schema version of one parsed document; 0 when the field is absent.

    A missing or non-integer field means the file predates versioning and is
    legal as version 0.
    """
    if not isinstance(document, dict):
        return 0
    field = (
        SNAPSHOT_SCHEMA_VERSION_FIELD if file_type == ENGINEERING_SNAPSHOT else SCHEMA_VERSION_FIELD
    )
    version = document.get(field)
    if isinstance(version, bool) or not isinstance(version, int):
        return 0
    return max(version, 0)


def supported_schema_version(file_type: str) -> int:
    """The newest schema version this ECC supports for *file_type*."""
    if file_type in SUPPORTED_SCHEMA_VERSIONS:
        return SUPPORTED_SCHEMA_VERSIONS[file_type]
    return max(SCHEMA_MIGRATIONS[file_type])


def ensure_supported_schema_version(file_type: str, path: Path | str, document: object) -> int:
    """Return the document's schema version, rejecting versions newer than supported."""
    version = document_schema_version(document, file_type)
    supported = supported_schema_version(file_type)
    if version > supported:
        raise UnsupportedSchemaVersionError(path, version, supported)
    return version


def _versioned_file_path(file_type: str, workspace_dir: str | Path) -> Path | None:
    """The one versioned file behind *file_type*, or None for directory-wide types.

    The single-file type constants double as their filenames under ``home/``.
    """
    if file_type in (PARAMS_TOML, FLOW_JSON, ENGINEERING_SNAPSHOT):
        return Path(workspace_dir) / "home" / file_type
    return None


def read_file_schema_version(file_type: str, workspace_dir: str | Path) -> int:
    """The on-disk schema version of *file_type*; 0 when absent or unreadable."""
    path = _versioned_file_path(file_type, workspace_dir)
    if path is None or not path.is_file():
        return 0
    if file_type == PARAMS_TOML:
        try:
            with open(path, "rb") as f:
                document: Any = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
            return 0
    else:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return 0
    return document_schema_version(document, file_type)


def apply_schema_migrations(file_type: str, workspace_dir: str | Path) -> int:
    """Apply the registered migration chain for *file_type* at workspace open.

    Starts from the file's current version (0 when the field is absent) and
    runs every registered migration targeting a newer version, in ascending
    order. Returns the resulting version. Raises
    UnsupportedSchemaVersionError when the file declares a version newer
    than supported — the file is never parsed past that point.
    """
    workspace_dir = Path(workspace_dir)
    version = read_file_schema_version(file_type, workspace_dir)
    supported = supported_schema_version(file_type)
    if version > supported:
        path = _versioned_file_path(file_type, workspace_dir) or workspace_dir
        raise UnsupportedSchemaVersionError(path, version, supported)
    for target in sorted(k for k in SCHEMA_MIGRATIONS.get(file_type, {}) if k > version):
        SCHEMA_MIGRATIONS[file_type][target](workspace_dir)
        version = target
    return version
