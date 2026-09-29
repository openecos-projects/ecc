import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from chipcompiler.utility import JsonReadError, json_read_strict

ENGINEERING_SNAPSHOT_MAX_BYTES = 16 * 1024 * 1024
CHECKLIST_READ_MAX_BYTES = 1024 * 1024

BoundedJsonStatus = Literal["available", "missing", "invalid", "oversized"]


@dataclass(frozen=True)
class BoundedJsonObject:
    status: BoundedJsonStatus
    data: dict[str, Any] | None


def encoded_json_size(value: object) -> int:
    """Size of the compact serialization that ``json_write(..., indent=None)`` emits."""
    return len(json.dumps(value).encode("utf-8"))


def read_bounded_json_object(path: Path, max_bytes: int) -> BoundedJsonObject:
    try:
        if not path.is_file():
            return BoundedJsonObject("missing", None)
        if path.stat().st_size > max_bytes:
            return BoundedJsonObject("oversized", None)
        data = json_read_strict(path)
    except (OSError, JsonReadError):
        return BoundedJsonObject("invalid", None)
    if not isinstance(data, dict):
        return BoundedJsonObject("invalid", None)
    if encoded_json_size(data) > max_bytes:
        return BoundedJsonObject("oversized", None)
    return BoundedJsonObject("available", data)
