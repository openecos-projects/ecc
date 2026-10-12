import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from chipcompiler.engine.snapshot import (
    SNAPSHOT_FILENAME,
    EngineeringSnapshotError,
    read_engineering_snapshot_from_directory,
)
from chipcompiler.engine.snapshot_limits import ENGINEERING_SNAPSHOT_MAX_BYTES


class SnapshotDestinationError(ValueError):
    pass


@dataclass(frozen=True)
class SnapshotExport:
    path: Path
    source: Path
    schema_version: int
    workspace_id: str
    workspace_revision: int
    bytes_written: int


def save_engineering_snapshot(directory: str | Path, output_path: str | Path) -> SnapshotExport:
    workspace_root = Path(directory).expanduser().resolve()
    try:
        if not str(output_path):
            raise SnapshotDestinationError("--output must name a JSON file")
        requested = Path(output_path).expanduser().absolute()
        destination = requested.parent.resolve(strict=True) / requested.name
        if not destination.parent.is_dir():
            raise SnapshotDestinationError("output parent must be an existing directory")
        if destination.is_relative_to(workspace_root):
            raise SnapshotDestinationError("output must be outside the source workspace")
        if destination.suffix == ".gz":
            raise SnapshotDestinationError("output must be uncompressed JSON, not .gz")
        if os.path.lexists(destination):
            raise FileExistsError(f"output already exists: {destination}")
    except (FileNotFoundError, NotADirectoryError, RuntimeError) as exc:
        raise SnapshotDestinationError(f"invalid output destination: {output_path}") from exc

    snapshot = read_engineering_snapshot_from_directory(workspace_root)
    content = json.dumps(snapshot, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(content) > ENGINEERING_SNAPSHOT_MAX_BYTES:
        raise EngineeringSnapshotError("saved Engineering Snapshot exceeds the file size limit")

    descriptor, temporary = tempfile.mkstemp(prefix=".ecc-snapshot-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    finally:
        os.unlink(temporary)

    return SnapshotExport(
        path=destination,
        source=workspace_root / "home" / SNAPSHOT_FILENAME,
        schema_version=snapshot["schemaVersion"],
        workspace_id=snapshot["workspaceId"],
        workspace_revision=snapshot["workspaceRevision"],
        bytes_written=len(content),
    )
