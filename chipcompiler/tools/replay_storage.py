"""Attempt identity and atomic publication shared by Replay producers and the flow."""

import json
import tempfile
from pathlib import Path

from chipcompiler.utility.workspace_lock import workspace_lock


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=path.name, delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def replay_root(step) -> Path | None:
    geometry = getattr(step.output, "geometry", None)
    output = getattr(step.output, "dir", None)
    if geometry:
        return Path(geometry) / "replay"
    if output:
        return Path(output) / "geometry/replay"
    if getattr(step, "directory", None):
        return Path(step.directory) / "output/geometry/replay"
    return None


def read_pointer(root: Path) -> dict:
    path = root / "manifest.json"
    return json.loads(path.read_text()) if path.exists() else {}


def update_pointer(root: Path, value: dict, *, expected: str | None = None) -> bool:
    """Only the still-current attempt may complete or fail a recording."""
    with workspace_lock(root):
        if expected is not None and read_pointer(root).get("attempt_id") != expected:
            return False
        atomic_json(root / "manifest.json", {"schema": "ecos.replay.v1", **value})
        return True


def within(root: Path, path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve(strict=True)):
        raise ValueError("Replay artifact path escapes its root")
    return resolved
