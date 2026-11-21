import fcntl
import json
import os
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import BinaryIO

_BACKUP_NAME = ".workspace-configuration-backup"
_DISCARD_NAME = f"{_BACKUP_NAME}.discard"
_ABSENT_MARKER = ".absent-paths.json"
_MAX_MANAGED_PATHS = 1024
_MAX_RELATIVE_PATH_LENGTH = 4096
_ACTIVE: set[Path] = set()


class WorkspaceFileTransaction:
    def __init__(self, workspace: Path, lock: BinaryIO):
        self.workspace = workspace
        self.lock = lock
        self.backup = workspace / "home" / _BACKUP_NAME
        self.finished = False

    @classmethod
    def begin(cls, workspace: str | Path, paths: Iterable[Path]) -> "WorkspaceFileTransaction":
        root = Path(workspace).expanduser().resolve()
        lock = _open_lock(_lock_path(root))
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            _recover_locked(root)
            transaction = cls(root, lock)
            transaction._prepare(paths)
            _ACTIVE.add(root)
            return transaction
        except BaseException:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()
            raise

    def commit(self) -> None:
        discard = self.workspace / "home" / _DISCARD_NAME
        if discard.exists():
            shutil.rmtree(discard)
        if self.backup.exists():
            self.backup.replace(discard)
            shutil.rmtree(discard)
        self._release()

    def rollback(self) -> None:
        try:
            _restore_backup(self.workspace, self.backup)
            shutil.rmtree(self.backup, ignore_errors=True)
        finally:
            self._release()

    def _prepare(self, paths: Iterable[Path]) -> None:
        home = self.workspace / "home"
        if home.is_symlink():
            raise OSError(f"Workspace home directory is a symlink: {home}")
        home.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(self.backup, ignore_errors=True)
        self.backup.mkdir(parents=True)
        managed = sorted(set(paths))
        if len(managed) > _MAX_MANAGED_PATHS:
            raise OSError("Workspace transaction path limit exceeded")
        absent: list[str] = []
        for path in managed:
            target = Path(path).resolve()
            relative = target.relative_to(self.workspace)
            _validate_relative_path(relative)
            if not target.exists():
                absent.append(relative.as_posix())
                continue
            if target.is_symlink() or not target.is_file():
                raise OSError(f"Workspace transaction target is not a regular file: {target}")
            destination = self.backup / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, destination)
        marker = self.backup / _ABSENT_MARKER
        with open(marker, "x", encoding="utf-8") as stream:
            json.dump({"schemaVersion": 1, "paths": absent}, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_directory(self.backup)
        _fsync_directory(self.backup.parent)

    def _release(self) -> None:
        if self.finished:
            return
        _ACTIVE.discard(self.workspace)
        fcntl.flock(self.lock.fileno(), fcntl.LOCK_UN)
        self.lock.close()
        self.finished = True


def recover_workspace_file_transaction(workspace: str | Path) -> None:
    root = Path(workspace).expanduser().resolve()
    if root in _ACTIVE:
        return
    home = root / "home"
    if not (home / _BACKUP_NAME).exists() and not (home / _DISCARD_NAME).exists():
        return
    with _open_lock(_lock_path(root)) as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            _recover_locked(root)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _recover_locked(workspace: Path) -> None:
    home = workspace / "home"
    if home.is_symlink():
        raise OSError(f"Workspace home directory is a symlink: {home}")
    discard = home / _DISCARD_NAME
    if discard.exists():
        shutil.rmtree(discard)
    backup = home / _BACKUP_NAME
    if backup.exists():
        _restore_backup(workspace, backup)
        shutil.rmtree(backup)


def _restore_backup(workspace: Path, backup: Path) -> None:
    if not backup.is_dir():
        return
    absent = _read_absent_marker(backup)
    for source in backup.rglob("*"):
        if not source.is_file() or source == backup / _ABSENT_MARKER:
            continue
        target = workspace / source.relative_to(backup)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for relative in absent:
        target = workspace / relative
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.exists():
            raise OSError(f"Workspace transaction cannot remove non-file target: {target}")


def _read_absent_marker(backup: Path) -> tuple[Path, ...]:
    marker = backup / _ABSENT_MARKER
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OSError(f"Invalid Workspace transaction marker: {marker}") from exc
    paths = payload.get("paths") if isinstance(payload, dict) else None
    if (
        payload.get("schemaVersion") != 1
        or not isinstance(paths, list)
        or len(paths) > _MAX_MANAGED_PATHS
    ):
        raise OSError(f"Invalid Workspace transaction marker: {marker}")
    result = []
    for value in paths:
        if not isinstance(value, str):
            raise OSError(f"Invalid Workspace transaction marker: {marker}")
        relative = Path(value)
        _validate_relative_path(relative)
        result.append(relative)
    return tuple(result)


def _validate_relative_path(path: Path) -> None:
    if (
        path.is_absolute()
        or not path.parts
        or ".." in path.parts
        or len(path.as_posix()) > _MAX_RELATIVE_PATH_LENGTH
        or path.parts[0] != "home"
        and path.parts[0] != "config"
    ):
        raise OSError(f"Invalid Workspace transaction path: {path}")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _lock_path(workspace: Path) -> Path:
    return workspace.parent / f".{workspace.name}.configuration.lock"


def _open_lock(path: Path) -> BinaryIO:
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    return os.fdopen(descriptor, "a+b")
