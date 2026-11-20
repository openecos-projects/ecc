"""Resolve a default only when creating a project, never when reopening one."""

import os
from pathlib import Path

from .documents import process_identity
from .managed import adopt_configuration, legacy_identity
from .manifest import DescriptorError, content_identity, load_descriptor
from .registry import default_installation


def selected_pdk(explicit_root: str | None, client: str) -> tuple[str, str]:
    if client not in {"ecc", "studio"}:
        raise DescriptorError("invalid_client", "PDK default client must be ecc or studio")
    record = None
    root = explicit_root or os.environ.get("ECC_PDK_ROOT")
    if not root:
        record = default_installation(client)
        root = record["root"] if record else None
    if not root:
        return "", ""
    path = Path(root).expanduser().resolve(strict=True)
    adopt_configuration(path)
    descriptor = load_descriptor(path)
    digest, hashes = content_identity(path, descriptor)
    expected = (record.get("pdkDigest") or record.get("contentDigest")) if record else None
    actual = process_identity(descriptor, hashes) if record and record.get("pdkDigest") else digest
    legacy_matches = (
        record
        and not record.get("pdkDigest")
        and expected == legacy_identity(path, descriptor, hashes)
    )
    if expected and expected != actual and not legacy_matches:
        raise DescriptorError("content_mismatch", "default PDK differs from its registered content")
    return descriptor.family_id, str(path)
