#!/usr/bin/env python

import hashlib
import os
import tempfile
from contextlib import suppress
from pathlib import Path


def write_text_atomic(path: str, text: str) -> None:
    """Replace the file at `path` with `text` via a sibling temp file + os.replace.

    A plain `open(path, "w")` truncates first, so an interruption or write
    failure after truncation can destroy the existing file; the sibling temp
    file keeps the old content intact until the fully written replacement
    can be renamed in. An existing file's permissions are preserved
    (mkstemp's 0600 would otherwise silently narrow a shared ecc.toml); a
    new file gets the umask-respecting default the plain write would have
    produced.
    """
    directory = os.path.dirname(os.path.abspath(path))
    try:
        mode = os.stat(path).st_mode & 0o7777
    except OSError:
        mode = 0o666 & ~_current_umask()
    fd, tmp_path = tempfile.mkstemp(
        dir=directory, prefix=f".{os.path.basename(path)}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except BaseException:
        os.unlink(tmp_path)
        raise


def _current_umask() -> int:
    """Read the process umask (querying requires setting it back)."""
    mask = os.umask(0o022)
    os.umask(mask)
    return mask


def chmod_folder(folder: str, mode: int = 0o777):
    def _try_chmod(path):
        with suppress(Exception):
            os.chmod(path, mode)

    for root, dirs, files in os.walk(folder):
        _try_chmod(root)
        for file in files:
            _try_chmod(os.path.join(root, file))
        for dir in dirs:
            full_path = os.path.join(root, dir)
            _try_chmod(full_path)


def find_files(directory: str, key: str):
    result_files = []
    for root, _dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(f"{key}"):
                result_files.append(os.path.join(root, file))
    return result_files


def file_digest(path: Path | str | None) -> tuple[str, int] | None:
    if not path:
        return None
    value = Path(path)
    try:
        size_bytes = value.stat().st_size
        digest = hashlib.sha256()
        with value.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest(), size_bytes
