"""Shared Studio/CLI inventory with a cross-process directory lock.

A lock left by a crashed process fails closed. Remove it only after confirming
no Studio/ECC inventory writer is running; no age-based lock stealing occurs.
"""

import hashlib
import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from .manifest import DescriptorError, content_identity, load_descriptor


def inventory_path() -> Path:
    explicit = os.environ.get("ECC_PDK_INVENTORY")
    if explicit:
        return Path(explicit).expanduser().resolve()
    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return state / "ecos-studio/resources/pdk-inventory.json"


@contextmanager
def inventory_transaction(path: Path | None = None):
    path = path or inventory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = Path(str(path) + ".lock")
    deadline = time.monotonic() + 10
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise DescriptorError(
                    "inventory_locked", f"PDK inventory is locked: {lock}"
                ) from None
            time.sleep(0.05)
    try:
        if path.exists():
            data = json.loads(path.read_text())
            if data.get("schemaVersion") != 1 or not all(
                isinstance(data.get(key), list) for key in ("installations", "bindings")
            ):
                raise DescriptorError("inventory_invalid", "unsupported PDK inventory")
        else:
            # Studio owns the migration of its old resource manifest.
            legacy = path.parent / "manifest.json"
            if legacy.exists():
                old = json.loads(legacy.read_text())
                if any(v.get("type") == "pdk" for v in old.get("installed", {}).values()):
                    raise DescriptorError(
                        "migration_required", "open Studio once to migrate its legacy PDK inventory"
                    )
            data = {"schemaVersion": 1, "installations": [], "bindings": []}
        before = json.dumps(data, sort_keys=True)
        yield data
        if json.dumps(data, sort_keys=True) != before:
            if path.is_symlink():
                raise DescriptorError("unsafe_path", "PDK inventory must not be a symlink")
            fd, temporary = tempfile.mkstemp(prefix=".pdk-inventory-", dir=path.parent)
            try:
                with os.fdopen(fd, "w") as stream:
                    json.dump(data, stream, indent=2)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)
    finally:
        lock.rmdir()


def register(root: Path) -> dict:
    root = root.expanduser().resolve(strict=True)
    descriptor = load_descriptor(root)
    digest, _ = content_identity(root, descriptor)
    with inventory_transaction() as inventory:
        existing = next((r for r in inventory["installations"] if r["root"] == str(root)), None)
        if existing:
            previous = existing.get("contentDigest")
            if previous and previous != digest:
                raise DescriptorError(
                    "content_mismatch",
                    "registered PDK changed; import a separate immutable release",
                )
            return existing
        identity = hashlib.sha256(str(root).encode()).hexdigest()[:16]
        record = {
            "id": f"pdk:{descriptor.family_id}:local:{identity}",
            "familyId": descriptor.family_id,
            "displayName": descriptor.family_id,
            "version": descriptor.release or None,
            "root": str(root),
            "ownership": "imported",
            "registrySha256": None,
            "contentDigest": digest,
        }
        inventory["installations"].append(record)
        return record


def set_default(installation_id: str, client: str) -> None:
    if client not in {"ecc", "studio"}:
        raise DescriptorError("invalid_client", "default client must be ecc or studio")
    with inventory_transaction() as inventory:
        if not any(r["id"] == installation_id for r in inventory["installations"]):
            raise DescriptorError("installation_missing", "unknown PDK installation")
        inventory.setdefault("defaults", {})[client] = installation_id


def default_installation(client: str = "ecc") -> dict | None:
    if not inventory_path().exists():
        return None
    with inventory_transaction() as inventory:
        identity = inventory.get("defaults", {}).get(client)
        return next((r for r in inventory["installations"] if r["id"] == identity), None)


def relocate(installation_id: str, root: Path) -> dict:
    root = root.expanduser().resolve(strict=True)
    descriptor = load_descriptor(root)
    digest, _ = content_identity(root, descriptor)
    with inventory_transaction() as inventory:
        record = next((r for r in inventory["installations"] if r["id"] == installation_id), None)
        if record is None:
            raise DescriptorError("installation_missing", "unknown PDK installation")
        expected = record.get("contentDigest")
        if not expected:
            old_root = Path(record["root"])
            expected, _ = content_identity(old_root, load_descriptor(old_root))
        if expected != digest:
            raise DescriptorError("content_mismatch", "relocation requires identical PDK content")
        record.update(root=str(root), contentDigest=digest)
        return record
