"""Retain-backup support for in-place Workspace updates.

An in-place update atomically exchanges the Workspace directory with a
fully constructed staging tree; the staging path then holds the REPLACED
tree, which the update normally deletes. A retaining update instead renames
it to a hidden sibling ``.<name>.replace-backup-<N>`` (the lowest free N,
mirroring the Studio GUI's replacement-backup naming), keeping the replaced
generation — including its old Engineering Snapshot — next to the
Workspace.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def retain_replaced_tree(staging: Path, target: Path) -> Path | None:
    """Rename the replaced tree at *staging* to a replace-backup sibling.

    This runs only after the update has committed, so a failure must not
    fail the update — and must not delete a tree the caller asked to retain
    either: a failed rename returns None and leaves the tree at *staging*
    (the caller skips its staging cleanup on our say-so), logged for
    diagnosis. Returns the backup directory on success.
    """
    backup = _free_backup_path(target)
    try:
        os.rename(staging, backup)
    except OSError as exc:
        logger.warning(
            "replaced Workspace tree left at staging path %s: backup rename to %s failed: %s",
            staging,
            backup,
            exc,
        )
        return None
    return backup


def _free_backup_path(target: Path) -> Path:
    number = 1
    while True:
        candidate = target.parent / f".{target.name}.replace-backup-{number}"
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
        number += 1
