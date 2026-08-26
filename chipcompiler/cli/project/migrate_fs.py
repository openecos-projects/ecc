#!/usr/bin/env python

"""Filesystem transaction mechanics for ``ecc migrate``.

Dir-handle anchored moves: the ``runs/`` container is opened once with
``O_NOFOLLOW`` and fstat-bound to its plan-time identity, each source is
checked and addressed relative to that confirmed handle, and every move
goes through ``renameat2(RENAME_NOREPLACE)`` — target collision is
enforced by the primitive itself, never by a check-then-act pair.
"""

import ctypes
import errno
import json
import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

RENAME_NOREPLACE = 1


def _load_renameat2():
    """The raw renameat2 syscall wrapper, or None when unavailable."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = libc.renameat2
    except (OSError, AttributeError):
        return None
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    return renameat2


_renameat2 = _load_renameat2()


def open_container(runs_dir: str):
    """Open the runs/ container without following symlinks.

    Returns (fd, (dev, ino)) on success, or (None, reason). A symlinked
    or otherwise unopenable container is refused here — before any
    enumeration.
    """
    try:
        fd = os.open(runs_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        return None, f"runs/ is not a real directory ({exc.strerror or exc})"
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode):
        os.close(fd)
        return None, "runs/ is not a directory"
    return fd, (info.st_dev, info.st_ino)


def child_stat(container_fd: int, name: str):
    """fstatat(name, dir_fd, nofollow); None when the child vanished."""
    try:
        return os.stat(name, dir_fd=container_fd, follow_symlinks=False)
    except OSError:
        return None


def move_noreplace(src_fd: int, src_name: str, dst_fd: int, dst_name: str) -> int:
    """renameat2(RENAME_NOREPLACE); 0 on success, an errno otherwise."""
    if _renameat2 is None:
        return errno.ENOSYS
    rc = _renameat2(
        src_fd,
        os.fsencode(src_name),
        dst_fd,
        os.fsencode(dst_name),
        RENAME_NOREPLACE,
    )
    return 0 if rc == 0 else ctypes.get_errno()


def move_back(
    container_fd: int,
    project_fd: int,
    name: str,
    target_path: str,
    expect_identity: tuple[int, int],
) -> bool:
    """Move a migrated workspace back under runs/ when identity permits.

    The object at *target_path* must be the confirmed moved one
    (identity checked first), and the source name must still be free
    (NOREPLACE enforced by the primitive). Touching neither object when
    recovery is impossible returns False.
    """
    try:
        target_stat = os.lstat(target_path)
    except OSError:
        return True  # nothing at the target to move back
    if (target_stat.st_dev, target_stat.st_ino) != expect_identity:
        logger.warning("rollback skipped: target is not the moved object: %s", target_path)
        return False
    rc = move_noreplace(project_fd, name, container_fd, name)
    if rc == 0:
        return True
    logger.warning("rollback move-back failed for %s: %s", target_path, os.strerror(rc))
    return False


def _contains_symlink(root: str) -> bool:
    """Any symlink anywhere below root (walk never follows links)."""
    for dirpath, dirnames, filenames in os.walk(root):
        for name in (*dirnames, *filenames):
            if os.path.islink(os.path.join(dirpath, name)):
                return True
    return False


def _unsafe_workspace_source(source: str) -> str | None:
    """Why this run source is unsafe to migrate, or None.

    The source and every workspace-local path the migration mutates
    (home/, config/, recursively) must be real, non-symlink filesystem
    objects owned by that workspace.
    """
    if os.path.islink(source) or not os.path.isdir(source):
        return "run source is not a real directory"
    for sub in ("home", "config"):
        sub_path = os.path.join(source, sub)
        if os.path.islink(sub_path):
            return f"{sub} is a symlink"
        if os.path.isdir(sub_path) and _contains_symlink(sub_path):
            return f"{sub} contains a symlink"
    return None


def _rebase_home_pointers(workspace_dir: str, old_prefix: str, new_prefix: str) -> None:
    """Rewrite home.json path values from the old workspace location."""
    home_path = os.path.join(workspace_dir, "home", "home.json")
    with open(home_path, encoding="utf-8") as f:
        data = json.load(f)

    def rebase(value):
        if isinstance(value, str):
            if value == old_prefix or value.startswith(old_prefix + os.sep):
                return new_prefix + value[len(old_prefix) :]
            return value
        if isinstance(value, dict):
            return {key: rebase(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rebase(item) for item in value]
        return value

    rebased = {key: rebase(value) for key, value in data.items()}
    from chipcompiler.utility import json_write

    if not json_write(home_path, rebased):
        raise OSError(f"failed to write rebased home.json: {home_path}")


def _rollback_workspace(entry, container_fd: int, project_fd: int) -> bool:
    """Undo a failed move when identity permits; touch nothing otherwise.

    The object is moved back under runs/ only when it is the confirmed
    moved inode and the source name is still free; reverse-rebase and
    config refresh run only while the moved object remains
    identity-confirmed. Returns True when the workspace is restored at
    its source (or never left), False when recovery was impossible
    without touching unconfirmed objects.
    """
    if not move_back(
        container_fd,
        project_fd,
        entry.run_id,
        entry.target,
        (entry.source_dev, entry.source_ino),
    ):
        return False
    try:
        _rebase_home_pointers(entry.source, entry.target, entry.source)
    except (OSError, json.JSONDecodeError):
        logger.warning("rollback: home.json reverse rebase failed for %s", entry.run_id)
    try:
        from chipcompiler.data import load_workspace, refresh_workspace_config

        workspace = load_workspace(entry.source)
        if workspace is not None:
            refresh_workspace_config(workspace)
    except Exception:
        logger.warning("rollback: config regeneration failed for %s", entry.run_id)
    return True


def _pre_rebase_legacy_config_paths(workspace_dir: str, old_prefix: str, new_prefix: str) -> None:
    """Rebase workspace-local pdk config paths BEFORE the moved workspace loads.

    Both the legacy parameters.json ("PDK Config") and an already-migrated
    home/ecc.toml can carry an absolute path under the old location; the
    workspace cannot load while the path points back at the old source.
    """
    legacy_path = Path(workspace_dir) / "home" / "parameters.json"
    if legacy_path.exists():
        data = json.loads(legacy_path.read_text(encoding="utf-8"))
        value = data.get("PDK Config")
        if isinstance(value, str) and value.startswith(old_prefix + os.sep):
            data["PDK Config"] = new_prefix + value[len(old_prefix) :]
            legacy_path.write_text(json.dumps(data), encoding="utf-8")

    config_path = Path(workspace_dir) / "home" / "ecc.toml"
    if config_path.exists():
        from chipcompiler.data.parameter import load_parameter, save_parameter

        parameters = load_parameter(config_path)
        value = parameters.data.get("pdk_config")
        if isinstance(value, str) and value.startswith(old_prefix + os.sep):
            parameters.data["pdk_config"] = new_prefix + value[len(old_prefix) :]
            if not save_parameter(parameters):
                raise OSError(f"failed to rebase workspace config paths: {workspace_dir}")


def _move_workspace(entry, container_fd: int, project_fd: int) -> tuple[str, str] | None:
    """Move one confirmed workspace and rebase it; (error_kind, reason) or None.

    The source is checked and addressed relative to the confirmed runs/
    handle (fstatat against the plan-time identity), and the move itself
    is the atomic no-replace primitive — target collision is enforced by
    the syscall, never by a lexists-then-rename pair. Immediately after
    the move, the target must match the plan-time source identity and
    stay free of symlink components before any load, rebase, or refresh.
    Recovery touches only identity-confirmed objects.
    """
    try:
        child = child_stat(container_fd, entry.run_id)
        if child is None:
            return ("migration_failed", "run source vanished after preview")
        if stat.S_ISLNK(child.st_mode):
            return ("migration_failed", "unsafe run source: run source is a symlink")
        if (child.st_dev, child.st_ino) != (entry.source_dev, entry.source_ino):
            return ("migration_failed", "run source changed after preview")
        rc = move_noreplace(container_fd, entry.run_id, project_fd, entry.run_id)
        if rc == errno.ENOSYS:
            return (
                "migration_failed",
                "atomic no-replace move is unavailable on this platform",
            )
        if rc in (errno.EEXIST, errno.ENOTEMPTY):
            return (
                "migration_collision",
                f"{entry.run_id} appeared at the project root after preview",
            )
        if rc != 0:
            return ("migration_failed", f"move failed: {os.strerror(rc)}")

        target_stat = os.lstat(entry.target)
        revalidate_reason = _unsafe_workspace_source(entry.target)
        if (target_stat.st_dev, target_stat.st_ino) != (
            entry.source_dev,
            entry.source_ino,
        ) or revalidate_reason is not None:
            # Possible source substitution inside the move: move the
            # just-moved object back (identity-bound), without
            # load_workspace, rebasing, or refresh.
            moved_back = move_back(
                container_fd,
                project_fd,
                entry.run_id,
                entry.target,
                (target_stat.st_dev, target_stat.st_ino),
            )
            reason = (
                "moved target failed revalidation "
                f"({revalidate_reason or 'identity changed after rename'})"
            )
            if not moved_back:
                reason += "; rollback incomplete: the object was left at the project root"
            return ("migration_failed", reason)
        from chipcompiler.data import load_workspace, refresh_workspace_config

        _pre_rebase_legacy_config_paths(entry.target, entry.source, entry.target)
        workspace = load_workspace(entry.target)
        if workspace is None:
            raise ValueError(f"moved workspace fails to load: {entry.target}")
        _rebase_home_pointers(entry.target, entry.source, entry.target)
        workspace = load_workspace(entry.target)
        refresh_workspace_config(workspace)
    except Exception as exc:
        if _rollback_workspace(entry, container_fd, project_fd):
            return ("migration_failed", str(exc))
        return (
            "migration_failed",
            f"{exc}; rollback incomplete: the moved workspace was left at {entry.target}",
        )
    return None
