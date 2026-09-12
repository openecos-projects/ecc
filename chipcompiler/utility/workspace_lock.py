import threading
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no sibling flock.
    fcntl = None

_local = threading.local()
_locks_guard = threading.Lock()
_locks: dict[str, threading.RLock] = {}


@contextmanager
def workspace_lock(directory: str | Path, *, blocking: bool = True):
    """Share the sibling Workspace lock across Engine and Runtime callers."""
    path = Path(directory).expanduser().resolve()
    key = str(path)
    held = getattr(_local, "held", set())
    if key in held:
        yield
        return

    with _locks_guard:
        lock = _locks.setdefault(key, threading.RLock())
    if not lock.acquire(blocking=blocking):
        raise BlockingIOError(f"Workspace lock is busy: {path}")

    lock_file = None
    file_locked = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if fcntl is not None:
            lock_file = (path.parent / f"{path.name}.lock").open("a")
            flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
            fcntl.flock(lock_file.fileno(), flags)
            file_locked = True
        held = set(held)
        held.add(key)
        _local.held = held
        yield
    finally:
        if key in getattr(_local, "held", set()):
            remaining = set(_local.held)
            remaining.remove(key)
            _local.held = remaining
        if lock_file is not None:
            try:
                if file_locked:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            finally:
                lock_file.close()
        lock.release()
