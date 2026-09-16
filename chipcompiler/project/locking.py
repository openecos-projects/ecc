"""Project-domain file lock helper."""

import fcntl
from contextlib import contextmanager


@contextmanager
def flock_file(path: str, *, exclusive: bool = True):
    with open(path, "a") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield lock_file
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
