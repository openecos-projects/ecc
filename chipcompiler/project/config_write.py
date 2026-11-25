"""Serialize project configuration edits with Manifest and draft publication."""

from collections.abc import Callable
from pathlib import Path

from chipcompiler.project.manifest_write import manifest_lock
from chipcompiler.utility.file import write_text_atomic


def edit_project_config(config_path: str | Path, edit: Callable[[str], str | None]) -> bool:
    """Read and edit the latest configuration under the Project write lock."""
    path = Path(config_path)
    with manifest_lock(path.parent):
        original = path.read_text(encoding="utf-8")
        updated = edit(original)
        if updated is None:
            return False
        if updated != original:
            write_text_atomic(path, updated)
        return True
