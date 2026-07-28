#!/usr/bin/env python3
import os
import pathlib
import re
import sys


def read_version(path: str, pattern: str) -> str:
    text = pathlib.Path(path).read_text()
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1) if match else ""


def normalize_expected_version(expected_ref: str) -> str:
    if not expected_ref:
        return ""
    if expected_ref.startswith("refs/tags/v"):
        return expected_ref.removeprefix("refs/tags/v")
    if expected_ref.startswith("refs/heads/release/v"):
        return expected_ref.removeprefix("refs/heads/release/v")
    if expected_ref.startswith("release/v"):
        return expected_ref.removeprefix("release/v")
    if expected_ref.startswith("v"):
        return expected_ref.removeprefix("v")

    print(f"ERROR: unsupported expected ref '{expected_ref}'", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    py_ver = read_version("pyproject.toml", r'^version\s*=\s*"([^"]+)"')
    init_ver = read_version("chipcompiler/__init__.py", r'^__version__\s*=\s*"([^"]+)"')
    expected_ref = os.environ.get("EXPECTED_REF") or os.environ.get("EXPECTED_TAG") or ""

    print(f"pyproject.toml version: {py_ver}")
    print(f"chipcompiler/__version__: {init_ver}")

    if not py_ver or not init_ver:
        print(
            f"ERROR: missing version metadata. pyproject.toml='{py_ver}' "
            f"chipcompiler/__version__='{init_ver}'",
            file=sys.stderr,
        )
        return 1

    if py_ver != init_ver:
        print(
            f"ERROR: version mismatch. pyproject.toml='{py_ver}' "
            f"chipcompiler/__version__='{init_ver}'",
            file=sys.stderr,
        )
        return 1

    expected_version = normalize_expected_version(expected_ref)

    if expected_ref and not expected_version:
        print(f"ERROR: malformed expected ref '{expected_ref}'", file=sys.stderr)
        return 1

    if expected_version and expected_version != py_ver:
        print(f"ERROR: ref mismatch. ref='{expected_ref}' expected='v{py_ver}'", file=sys.stderr)
        return 1

    print(f"Version check passed: {py_ver}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
