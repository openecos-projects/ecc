#!/usr/bin/env python

import hashlib
import os
from contextlib import suppress
from pathlib import Path


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
