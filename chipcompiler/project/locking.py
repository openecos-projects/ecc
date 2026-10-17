"""Project-domain file lock helper."""

import fcntl
from contextlib import contextmanager


@contextmanager
def flock_file(path: str, *, exclusive: bool = True, blocking: bool = True):
    with open(path, "a") as lock_file:
        flags = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        if not blocking:
            flags |= fcntl.LOCK_NB
        fcntl.flock(lock_file.fileno(), flags)
        try:
            yield lock_file
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
