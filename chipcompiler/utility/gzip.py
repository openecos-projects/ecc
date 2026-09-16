#!/usr/bin/env python
import gzip
import os
from pathlib import Path


def read_text_maybe_gzip(
    path: str | os.PathLike,
    encoding: str = "utf-8",
    errors: str = "ignore",
) -> str:
    path_obj = Path(path)
    if path_obj.suffix == ".gz":
        # Some tools write plain text into a .gz-named file
        # (e.g. yosys built without zlib, or flows that fall back
        # to plain output for netlists larger than 2 GiB).
        # Check the gzip magic bytes instead of trusting the suffix,
        # otherwise gzip.open raises BadGzipFile (an OSError) that
        # callers silently swallow.
        with path_obj.open("rb") as file:
            is_gzip = file.read(2) == b"\x1f\x8b"
        if is_gzip:
            with gzip.open(path_obj, "rt", encoding=encoding, errors=errors) as file:
                return file.read()

    with path_obj.open("r", encoding=encoding, errors=errors) as file:
        return file.read()


def write_text_maybe_gzip(
    path: str | os.PathLike,
    text: str,
    encoding: str = "utf-8",
) -> None:
    path_obj = Path(path)
    if path_obj.suffix == ".gz":
        with gzip.open(path_obj, "wt", encoding=encoding) as file:
            file.write(text)
        return

    with path_obj.open("w", encoding=encoding) as file:
        file.write(text)
