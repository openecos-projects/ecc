"""Bounded, workspace-contained artifact evidence shared by CLI reports."""

import hashlib
from pathlib import Path


def inspect_artifact(root: Path, reference: str | Path, *, include_hash: bool = False) -> dict:
    root = root.resolve()
    try:
        candidate = Path(reference).expanduser()
        candidate = (candidate if candidate.is_absolute() else root / candidate).resolve()
        relative = candidate.relative_to(root).as_posix()
    except (OSError, RuntimeError, ValueError):
        return {"path": str(reference), "availability": "outside_workspace"}

    result = {"path": relative, "availability": "missing", "exists": False, "bytes": None}
    try:
        if not candidate.is_file():
            return result
        result["exists"] = True
        result["bytes"] = candidate.stat().st_size
        result["availability"] = "available"
        if include_hash:
            digest = hashlib.sha256()
            with candidate.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            result["sha256"] = digest.hexdigest()
    except (OSError, RuntimeError, ValueError):
        result["availability"] = "unreadable"
    return result
