"""Content identities for sealed, self-contained recording payloads."""

import hashlib
from pathlib import Path


def fingerprint(path: Path):
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"size": path.stat().st_size, "sha256": digest}


def inventory(directory: Path):
    return {
        path.relative_to(directory).as_posix(): fingerprint(path)
        for path in sorted((directory / "subflows").rglob("*"))
        if path.is_file()
    }
