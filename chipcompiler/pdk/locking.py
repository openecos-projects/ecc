"""Portable content locks: relocation is allowed, replacement is not."""

import json
from pathlib import Path

from chipcompiler.utility.file import write_text_atomic
from chipcompiler.utility.workspace_lock import workspace_lock

from .manifest import Descriptor, DescriptorError, StrictModel, content_identity


class PdkLock(StrictModel):
    schema_version: int = 1
    digest: str
    descriptor: Descriptor
    resources: dict[str, str]


def build_lock(root: Path, descriptor: Descriptor) -> PdkLock:
    digest, resources = content_identity(root, descriptor)
    return PdkLock(digest=digest, descriptor=descriptor, resources=resources)


def read_lock(path: Path) -> PdkLock:
    lock = PdkLock.model_validate_json(path.read_bytes())
    if lock.schema_version != 1:
        raise DescriptorError("schema_unsupported", "unsupported PDK lock schema")
    return lock


def verify_lock(root: Path, lock: PdkLock) -> None:
    actual = build_lock(root, lock.descriptor)
    if actual != lock:
        raise DescriptorError("content_mismatch", "PDK resources differ from the project lock")


def bind_project(project: Path, root: Path, descriptor: Descriptor) -> PdkLock:
    lock = build_lock(root, descriptor)
    path = project / "pdk.lock.json"
    with workspace_lock(project):
        if path.is_symlink():
            raise DescriptorError("unsafe_path", "PDK lock must not be a symlink")
        if path.exists():
            if read_lock(path) != lock:
                raise DescriptorError(
                    "project_pdk_immutable",
                    "copy the project to select another PDK or configuration revision",
                )
        else:
            write_text_atomic(str(path), json.dumps(lock.model_dump(), indent=2) + "\n")
    return lock


def lock_workspace_inputs(project: Path, root: Path, family: str) -> Path:
    """Pin the selected description before creating any workspace outputs."""
    from .manifest import load_descriptor

    descriptor = load_descriptor(root)
    if descriptor.family_id.casefold() != family.casefold():
        raise DescriptorError("family_mismatch", "project and PDK description families differ")
    bind_project(project, root, descriptor)
    # The project lock carries the authoritative snapshot; the creator receives
    # a normal descriptor so its existing pdk_config snapshot protocol applies.
    path = project / ".ecc-pdk-snapshot.json"
    content = json.dumps(descriptor.model_dump(), indent=2) + "\n"
    with workspace_lock(project):
        if path.is_symlink():
            raise DescriptorError("unsafe_path", "PDK snapshot must not be a symlink")
        write_text_atomic(str(path), content)
    return path
