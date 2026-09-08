"""Non-persisting checklist rendering for read-only package inspection."""

from pathlib import Path

from chipcompiler.data import Checklist


def render_checklist(path: Path | str, items, *, persist: bool = False) -> dict:
    if persist:
        checklist = Checklist(path)
        checklist.replace(list(items))
        return checklist.data
    return Checklist.from_items(path, items)
