"""Resolve a default only when creating a project, never when reopening one."""

import os
from pathlib import Path

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
    descriptor = load_descriptor(path)
    digest, _ = content_identity(path, descriptor)
    if record and record.get("contentDigest") and record["contentDigest"] != digest:
        raise DescriptorError("content_mismatch", "default PDK differs from its registered content")
    return descriptor.family_id, str(path)
