"""Atomic draft editing used by both interactive clients and the JSON CLI."""

import json
import os
import tempfile
from pathlib import Path

from chipcompiler.utility.workspace_lock import workspace_lock

from .manifest import Descriptor, DescriptorError, StrictModel, file_digest


def write_descriptor(
    path: Path, descriptor: StrictModel, *, expected_digest: str | None = None, create: bool = False
) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with workspace_lock(path.parent):
        if path.is_symlink():
            raise DescriptorError("unsafe_path", "descriptor output must not be a symlink")
        if create and path.exists():
            raise DescriptorError("already_exists", f"descriptor already exists: {path}")
        if expected_digest is not None and (
            not path.is_file() or file_digest(path) != expected_digest
        ):
            raise DescriptorError("revision_conflict", "descriptor changed; reload before saving")
        content = json.dumps(descriptor.model_dump(), indent=2, ensure_ascii=False) + "\n"
        fd, temporary = tempfile.mkstemp(prefix=".ecc-pdk-", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return file_digest(path)


def discover_resources(root: Path) -> list[dict[str, str]]:
    suffixes = {".lef": "lef", ".lib": "liberty", ".gds": "gds", ".v": "verilog"}
    candidates = []
    resolved = root.resolve()
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in suffixes or not path.is_file():
            continue
        if not path.resolve().is_relative_to(resolved):
            continue
        # Technology LEF selection and corner/VT assignment require confirmation.
        candidates.append(
            {
                "path": path.relative_to(root).as_posix(),
                "candidate_role": suffixes[path.suffix.lower()],
            }
        )
    return candidates


def replace_field(descriptor: Descriptor, field: str, value: object) -> Descriptor:
    data = descriptor.model_dump()
    keys = field.split(".")
    cursor = data
    for key in keys[:-1]:
        if key not in cursor or not isinstance(cursor[key], dict):
            raise DescriptorError("unknown_field", f"not an object field: {field}")
        cursor = cursor[key]
    cursor[keys[-1]] = value
    return Descriptor.model_validate(data)
