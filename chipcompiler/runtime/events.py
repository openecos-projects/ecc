import os
import sys
from contextlib import contextmanager, suppress


@contextmanager
def redirect_stdout_to_stderr():
    saved_stdout = sys.stdout
    saved_stderr = sys.stderr
    saved_stdout_fd = None
    saved_stderr_fd = None

    with suppress(Exception):
        sys.stdout.flush()
    with suppress(Exception):
        sys.stderr.flush()

    try:
        saved_stdout_fd = os.dup(1)
        saved_stderr_fd = os.dup(2)
        os.dup2(2, 1)
        sys.stdout = sys.stderr
    except OSError:
        with suppress(Exception):
            if saved_stdout_fd is not None:
                os.close(saved_stdout_fd)
            if saved_stderr_fd is not None:
                os.close(saved_stderr_fd)
        sys.stdout = sys.stderr
        try:
            yield
        finally:
            sys.stdout = saved_stdout
            sys.stderr = saved_stderr
        return

    try:
        yield
    finally:
        with suppress(Exception):
            sys.stdout.flush()
        with suppress(Exception):
            sys.stderr.flush()
        try:
            os.dup2(saved_stdout_fd, 1)
            os.dup2(saved_stderr_fd, 2)
        finally:
            os.close(saved_stdout_fd)
            os.close(saved_stderr_fd)
            sys.stdout = saved_stdout
            sys.stderr = saved_stderr
