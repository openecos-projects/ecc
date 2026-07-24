#!/usr/bin/env python
from pathlib import Path


def optional_path(path: str | Path | None) -> Path | None:
    return Path(path) if path else None


def path_list(paths: list) -> list[Path]:
    return [Path(path) for path in paths if path]


def path_text(path) -> str:
    return "" if path is None else str(path)


def path_is_within(path: Path, directory: Path) -> bool:
    try:
        return Path(path).resolve().is_relative_to(Path(directory).resolve())
    except OSError:
        return False


def stringify_paths(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: stringify_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [stringify_paths(item) for item in value]
    return value
