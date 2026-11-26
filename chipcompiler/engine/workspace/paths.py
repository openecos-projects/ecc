"""Canonical path-rewriting helpers for staged Workspace trees."""

import json
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from chipcompiler.data.workspace import Workspace

_TCL_SCRIPT_PATTERNS = ("*/data/*.tcl", "*/script/*.tcl")


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


def _is_skipped(relative: Path, skip_paths: frozenset[Path]) -> bool:
    return relative in skip_paths or any(parent in skip_paths for parent in relative.parents)


def rewrite_workspace_json_paths(
    root: Path,
    relocate: Callable[[str], str],
    *,
    skip_paths: frozenset[Path] = frozenset(),
) -> set[Path]:
    """Rewrite path strings in JSON files under *root*, returning changed relative paths."""
    from chipcompiler.utility import json_write

    changed: set[Path] = set()
    for path in root.rglob("*.json"):
        relative = path.relative_to(root)
        if _is_skipped(relative, skip_paths):
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rewritten = rewrite_json_value(value, relocate)
        if rewritten != value:
            if not json_write(path, rewritten):
                raise OSError(f"Failed to rewrite staged Workspace path: {path}")
            changed.add(relative)
    return changed


def rewrite_workspace_tcl_paths(
    root: Path,
    rewrite_text: Callable[[str], str],
    *,
    skip_paths: frozenset[Path] = frozenset(),
) -> set[Path]:
    """Rewrite path references in generated step Tcl scripts under *root*."""
    from chipcompiler.utility.file import write_text_atomic

    changed: set[Path] = set()
    for pattern in _TCL_SCRIPT_PATTERNS:
        for path in root.glob(pattern):
            relative = path.relative_to(root)
            if _is_skipped(relative, skip_paths):
                continue
            original = path.read_text(encoding="utf-8")
            updated = rewrite_text(original)
            if updated != original:
                write_text_atomic(path, updated)
                changed.add(relative)
    return changed


def finalize_staged_workspace(
    workspace: "Workspace",
    target_root: Path,
    *,
    include_tcl_scripts: bool = False,
) -> None:
    """Relocate a freshly built tree and record its final managed configuration."""
    from chipcompiler.data.workspace.config_manifest import record_derived_config

    source_root = workspace.directory
    source = str(source_root)
    target = str(target_root)
    rewrite_workspace_json_paths(
        source_root,
        lambda item: target + item[len(source) :] if item.startswith(source) else item,
    )
    if include_tcl_scripts:
        rewrite_workspace_tcl_paths(
            source_root,
            lambda text: text.replace(f"{source}/", f"{target}/"),
        )

    if not record_derived_config(workspace):
        raise OSError(f"Failed to record derived Workspace configuration: {source_root}")


def rewrite_workspace_params_toml(root: Path, relocate: Callable[[str], str]) -> None:
    """Rewrite path strings inside ``home/params.toml`` using *relocate*."""
    import tomli_w

    from chipcompiler.utility.file import write_text_atomic

    path = root / "home" / "params.toml"
    params = tomllib.loads(path.read_text(encoding="utf-8"))
    rewritten = rewrite_json_value(params, relocate)
    if params != rewritten:
        write_text_atomic(path, tomli_w.dumps(rewritten))
