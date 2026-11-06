"""Exact schema-version checks for workspace persistent files.

Only the current formats are supported. Older files are not upgraded: the
workspace must be recreated with this ECC. Files from a newer ECC are rejected
without being parsed past their version field.
"""

import json
import tomllib
from pathlib import Path
from typing import Any, Final

SCHEMA_VERSION_FIELD: Final = "schema_version"
SNAPSHOT_SCHEMA_VERSION_FIELD: Final = "schemaVersion"

PARAMS_TOML: Final = "params.toml"
FLOW_JSON: Final = "flow.json"
ENGINEERING_SNAPSHOT: Final = "engineering-snapshot.json"

SUPPORTED_SCHEMA_VERSIONS: Final[dict[str, int]] = {
    PARAMS_TOML: 2,
    # Steps record indexed directory names; legacy <step>_<tool> layouts are not
    # read by this ECC.
    FLOW_JSON: 2,
    ENGINEERING_SNAPSHOT: 6,
}


class UnsupportedSchemaVersionError(ValueError):
    """A workspace file is not in the exact format this ECC supports."""

    def __init__(self, path: Path | str, version: int, supported: int):
        if version < supported:
            message = (
                f"unsupported legacy schema_version {version} in {path} "
                f"(this ECC requires {supported}); create a new workspace; "
                "migration is not supported"
            )
        else:
            message = (
                f"unsupported schema_version {version} in {path} "
                f"(this ECC supports up to {supported}); upgrade ECC or restore the file"
            )
        super().__init__(message)
        self.path = Path(path)
        self.version = version
        self.supported = supported


def document_schema_version(document: object, file_type: str) -> int:
    """The document's declared schema version; 0 when absent or invalid."""
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
    return SUPPORTED_SCHEMA_VERSIONS[file_type]


def ensure_supported_schema_version(file_type: str, path: Path | str, document: object) -> int:
    """Return the document version, rejecting every version except the current one."""
    version = document_schema_version(document, file_type)
    supported = supported_schema_version(file_type)
    if version != supported:
        raise UnsupportedSchemaVersionError(path, version, supported)
    return version


def _versioned_file_path(file_type: str, workspace_dir: str | Path) -> Path | None:
    if file_type in (PARAMS_TOML, FLOW_JSON, ENGINEERING_SNAPSHOT):
        return Path(workspace_dir) / "home" / file_type
    return None


def read_file_schema_version(file_type: str, workspace_dir: str | Path) -> int:
    """The on-disk schema version; 0 when absent, unreadable or invalid."""
    path = _versioned_file_path(file_type, workspace_dir)
    if path is None or not path.is_file():
        return 0
    if file_type == PARAMS_TOML:
        try:
            with open(path, "rb") as stream:
                document: Any = tomllib.load(stream)
        except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
            return 0
    else:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return 0
    return document_schema_version(document, file_type)


def require_file_schema_version(file_type: str, workspace_dir: str | Path) -> int:
    """Require an existing workspace file to declare the current schema version."""
    workspace_dir = Path(workspace_dir)
    version = read_file_schema_version(file_type, workspace_dir)
    supported = supported_schema_version(file_type)
    if version != supported:
        path = _versioned_file_path(file_type, workspace_dir) or workspace_dir
        raise UnsupportedSchemaVersionError(path, version, supported)
    return version
