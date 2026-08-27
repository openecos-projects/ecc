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
import fcntl
import json
import logging
import os
import stat
from contextlib import contextmanager
from pathlib import Path

from typing_extensions import deprecated

logger = logging.getLogger(__name__)

RENAME_NOREPLACE = 1


@contextmanager
def flock_file(path: str, *, exclusive: bool):
    """Hold an flock on *path* for the with-block (kernel-released on death)."""
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@deprecated(
    "legacy runs/ -> manifest layout migration machinery; slated for removal "
    "after the transition period",
    category=None,
)
@contextmanager
def project_migrate_lock(project_dir: str, *, exclusive: bool):
    """Project-level migration lock (flock, cooperating writers only).

    ``ecc migrate`` holds it exclusive across the move+register
    transaction; ``ecc run`` holds it shared while creating a workspace,
    so a GUI/CLI run and a migration in the same project serialize
    instead of corrupting each other. A process dying mid-hold releases
    the lock via the kernel; the file itself is left in place like the
    sibling ``<workspace>.lock``.
    """
    with flock_file(os.path.join(project_dir, ".migrate.lock"), exclusive=exclusive):
        yield


@deprecated(
    "legacy runs/ -> manifest layout migration machinery; slated for removal "
    "after the transition period",
    category=None,
)
@contextmanager
def existing_workspace_execution_lock(workspace_dir: str):
    """Serialize a migration move with an active execution of the workspace.

    Runs hold the sibling ``<workspace>.lock`` for their whole execution.
    The lock is only opened when the file already exists — creating it
    here would leave runs/ non-empty after a full migration. A run that
    starts after this probe holds its own fresh lock, re-classifies the
    workspace under it, and finds the workspace moved: a clean error, not
    a race. (The create-vs-probe instant itself is a syscall-granularity
    residual, out of the documented threat model.)
    """
    lock_path = os.path.join(
        os.path.dirname(workspace_dir), os.path.basename(workspace_dir) + ".lock"
    )
    try:
        fd = os.open(lock_path, os.O_RDWR)  # deliberately no O_CREAT
    except OSError:
        yield
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@deprecated(
    "legacy runs/ -> manifest layout migration machinery; slated for removal "
    "after the transition period",
    category=None,
)
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


@deprecated(
    "legacy runs/ -> manifest layout migration machinery; slated for removal "
    "after the transition period",
    category=None,
)
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


@deprecated(
    "legacy runs/ -> manifest layout migration machinery; slated for removal "
    "after the transition period",
    category=None,
)
def child_stat(container_fd: int, name: str):
    """fstatat(name, dir_fd, nofollow); None when the child vanished."""
    try:
        return os.stat(name, dir_fd=container_fd, follow_symlinks=False)
    except OSError:
        return None


@deprecated(
    "legacy runs/ -> manifest layout migration machinery; slated for removal "
    "after the transition period",
    category=None,
)
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


@deprecated(
    "legacy runs/ -> manifest layout migration machinery; slated for removal "
    "after the transition period",
    category=None,
)
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
    (NOREPLACE enforced by the primitive). A missing target counts as
    recovered only when the child under the anchored container provably
    has the expected identity. Touching neither object when recovery is
    impossible returns False.
    """
    try:
        target_stat = os.lstat(target_path)
    except OSError:
        # Nothing at the target: recovery is real only when the anchored
        # source child independently proves to be the moved object.
        child = child_stat(container_fd, name)
        if child is not None and (child.st_dev, child.st_ino) == expect_identity:
            return True
        logger.warning(
            "rollback incomplete: moved object missing and source identity unproven: %s",
            target_path,
        )
        return False
    if (target_stat.st_dev, target_stat.st_ino) != expect_identity:
        logger.warning("rollback skipped: target is not the moved object: %s", target_path)
        return False
    rc = move_noreplace(project_fd, name, container_fd, name)
    if rc == 0:
        return True
    logger.warning("rollback move-back failed for %s: %s", target_path, os.strerror(rc))
    return False


@deprecated(
    "legacy runs/ -> manifest layout migration machinery; slated for removal "
    "after the transition period",
    category=None,
)
def _contains_symlink(root: str) -> bool:
    """Any symlink anywhere below root (walk never follows links)."""
    for dirpath, dirnames, filenames in os.walk(root):
        for name in (*dirnames, *filenames):
            if os.path.islink(os.path.join(dirpath, name)):
                return True
    return False


@deprecated(
    "legacy runs/ -> manifest layout migration machinery; slated for removal "
    "after the transition period",
    category=None,
)
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


@deprecated(
    "legacy runs/ -> manifest layout migration machinery; slated for removal "
    "after the transition period",
    category=None,
)
def _rebase_home_pointers(workspace_dir: str, old_prefix: str, new_prefix: str) -> None:
    """Rewrite home.json path values from the old workspace location."""
    home_path = os.path.join(workspace_dir, "home", "home.json")
    with open(home_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"home.json is not a JSON object: {home_path}")

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


@deprecated(
    "legacy runs/ -> manifest layout migration machinery; slated for removal "
    "after the transition period",
    category=None,
)
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
    restored = True
    try:
        # Reverse the pre-load config path retarget as well as home.json:
        # all-or-nothing covers the legacy "PDK Config" pointer too.
        _pre_rebase_legacy_config_paths(entry.source, entry.target, entry.source)
        _rebase_home_pointers(entry.source, entry.target, entry.source)
    except (OSError, ValueError):
        # ValueError covers JSONDecodeError/UnicodeDecodeError and the
        # not-an-object guard: a malformed state file only downgrades the
        # rollback's rebase step, never escapes as an uncaught exception.
        logger.warning("rollback: home.json reverse rebase failed for %s", entry.run_id)
        restored = False
    try:
        from chipcompiler.data import load_workspace, refresh_workspace_config

        workspace = load_workspace(entry.source)
        if workspace is not None:
            refresh_workspace_config(workspace)
    except Exception:
        logger.warning("rollback: config regeneration failed for %s", entry.run_id)
        restored = False
    # Back at the source but with stale rebased content is NOT a completed
    # rollback: the caller reports it as incomplete, not as rolled back.
    return restored


@deprecated(
    "legacy runs/ -> manifest layout migration machinery; slated for removal "
    "after the transition period",
    category=None,
)
def _pre_rebase_legacy_config_paths(workspace_dir: str, old_prefix: str, new_prefix: str) -> None:
    """Rebase workspace-local pdk config paths BEFORE the moved workspace loads.

    Both the legacy parameters.json ("PDK Config") and an already-migrated
    home/ecc.toml can carry an absolute path under the old location; the
    workspace cannot load while the path points back at the old source.
    """
    legacy_path = Path(workspace_dir) / "home" / "parameters.json"
    if legacy_path.exists():
        data = json.loads(legacy_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            value = data.get("PDK Config")
            if isinstance(value, str) and value.startswith(old_prefix + os.sep):
                data["PDK Config"] = new_prefix + value[len(old_prefix) :]
                from chipcompiler.utility import json_write

                if not json_write(legacy_path, data):
                    raise OSError(f"failed to rebase PDK Config in {legacy_path}")

    config_path = Path(workspace_dir) / "home" / "ecc.toml"
    if config_path.exists():
        from chipcompiler.data.parameter import load_parameter, save_parameter

        parameters = load_parameter(config_path)
        value = parameters.data.get("pdk_config")
        if isinstance(value, str) and value.startswith(old_prefix + os.sep):
            parameters.data["pdk_config"] = new_prefix + value[len(old_prefix) :]
            if not save_parameter(parameters):
                raise OSError(f"failed to rebase workspace config paths: {workspace_dir}")


@deprecated(
    "legacy runs/ -> manifest layout migration machinery; slated for removal "
    "after the transition period",
    category=None,
)
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
    # Serialize with an active run of this workspace: its sibling lock
    # is only opened when it already exists — creating it would leave
    # runs/ non-empty after a full migration. A run that starts after
    # this probe re-classifies under its own fresh lock and finds the
    # workspace moved (a clean error, not a race).
    with existing_workspace_execution_lock(entry.source):
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

            # Fail-loud gate before the first content write: if the moved
            # workspace was replaced since the move, refuse loudly and leave
            # the state for the user to inspect — never mutate or register
            # an unconfirmed object.
            current = os.lstat(entry.target)
            if (current.st_dev, current.st_ino) != (entry.source_dev, entry.source_ino):
                return (
                    "migration_failed",
                    "the moved workspace was replaced during migration; "
                    f"inspect {entry.target} and {entry.source} manually",
                )
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
