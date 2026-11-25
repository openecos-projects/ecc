"""Canonical path-rewriting helpers for staged Workspace trees."""

import json
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any


def replace_string_prefix(value: Any, source: str, target: str) -> Any:
    """Replace *source* prefix with *target* recursively across JSON-like data."""
    return rewrite_json_value(
        value,
        lambda item: target + item[len(source) :] if item.startswith(source) else item,
    )


def rewrite_json_value(value: Any, relocate: Callable[[str], str]) -> Any:
    """Apply *relocate* to every string leaf in a JSON-compatible structure."""
    if isinstance(value, str):
        return relocate(value)
    if isinstance(value, list):
        return [rewrite_json_value(item, relocate) for item in value]
    if isinstance(value, dict):
        return {key: rewrite_json_value(item, relocate) for key, item in value.items()}
    return value


def rewrite_workspace_json_paths(
    root: Path,
    relocate: Callable[[str], str],
    *,
    skip_paths: frozenset[Path] = frozenset(),
) -> None:
    """Rewrite path strings in all JSON files under *root*, skipping *skip_paths*."""
    from chipcompiler.utility import json_write

    for path in root.rglob("*.json"):
        relative = path.relative_to(root)
        if relative in skip_paths or any(parent in skip_paths for parent in relative.parents):
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rewritten = rewrite_json_value(value, relocate)
        if rewritten != value and not json_write(path, rewritten):
            raise OSError(f"Failed to rewrite staged Workspace path: {path}")


def rewrite_workspace_paths(
    source_root: Path,
    target_root: Path,
    *,
    include_tcl_scripts: bool = False,
) -> None:
    """Rewrite staged Workspace JSON files (and optionally generated Tcl scripts)."""
    source = str(source_root)
    target = str(target_root)
    rewrite_workspace_json_paths(
        source_root,
        lambda item: target + item[len(source) :] if item.startswith(source) else item,
    )
    if include_tcl_scripts:
        from chipcompiler.utility.file import write_text_atomic

        for pattern in ("*/data/*.tcl", "*/script/*.tcl"):
            for path in source_root.glob(pattern):
                original = path.read_text(encoding="utf-8")
                updated = original.replace(f"{source}/", f"{target}/")
                if updated != original:
                    write_text_atomic(path, updated)


def rewrite_workspace_params_toml(root: Path, relocate: Callable[[str], str]) -> None:
    """Rewrite path strings inside ``home/params.toml`` using *relocate*."""
    import tomli_w

    from chipcompiler.utility.file import write_text_atomic

    path = root / "home" / "params.toml"
    params = tomllib.loads(path.read_text(encoding="utf-8"))
    rewritten = rewrite_json_value(params, relocate)
    if params != rewritten:
        write_text_atomic(path, tomli_w.dumps(rewritten))
