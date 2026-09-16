import fcntl
import os
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import BinaryIO

_BACKUP_NAME = ".workspace-configuration-backup"
_DISCARD_NAME = f"{_BACKUP_NAME}.discard"
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
        for path in sorted(set(paths)):
            target = Path(path).resolve()
            relative = target.relative_to(self.workspace)
            if not target.is_file():
                continue
            destination = self.backup / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, destination)

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
    for source in backup.rglob("*"):
        if not source.is_file():
            continue
        target = workspace / source.relative_to(backup)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _lock_path(workspace: Path) -> Path:
    return workspace.parent / f".{workspace.name}.configuration.lock"


def _open_lock(path: Path) -> BinaryIO:
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    return os.fdopen(descriptor, "a+b")
