"""Shared helpers for auditable, child-workspace candidate artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

HASH_PREFIX = "sha256:"
_CANDIDATE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return f"{HASH_PREFIX}{hashlib.sha256(value).hexdigest()}"


def sha256_path(path: Path) -> str | None:
    path = Path(path)
    if path.is_file():
        return sha256_bytes(path.read_bytes())
    if path.is_dir():
        digest = hashlib.sha256()
        for child in sorted(path.rglob("*"), key=lambda item: item.as_posix()):
            if not child.is_file():
                continue
            digest.update(child.relative_to(path).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(child.read_bytes())
            digest.update(b"\0")
        return f"{HASH_PREFIX}{digest.hexdigest()}"
    return None


def validate_candidate_id(candidate_id: Any) -> str:
    if not isinstance(candidate_id, str) or not _CANDIDATE_ID_PATTERN.fullmatch(candidate_id):
        raise ValueError("candidate_id must use 1-128 ASCII letters, digits, '.', '_', '-', or ':'")
    return candidate_id


def read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {label}: {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"invalid {label}: {path}: expected JSON object")
    return payload


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        with suppress(OSError):
            os.unlink(temporary)
        raise


def workspace_relative_ref(workspace_directory: str | Path, path: Path) -> str:
    root = Path(workspace_directory).expanduser().resolve()
    resolved = Path(path).expanduser().resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError(f"candidate artifact path outside workspace: {resolved}") from error


def workspace_analysis_path(workspace_directory: str | Path, filename: str) -> Path:
    return Path(workspace_directory).expanduser().resolve() / "analysis" / filename
