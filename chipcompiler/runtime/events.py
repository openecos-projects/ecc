from __future__ import annotations

import os
import sys
from contextlib import contextmanager, suppress


@contextmanager
def redirect_stdout_to_stderr():
    saved_stdout = sys.stdout
    saved_stdout_fd = None

    with suppress(Exception):
        sys.stdout.flush()

    try:
        saved_stdout_fd = os.dup(1)
        os.dup2(2, 1)
        sys.stdout = sys.stderr
    except OSError:
        with suppress(Exception):
            if saved_stdout_fd is not None:
                os.close(saved_stdout_fd)
        sys.stdout = sys.stderr
        try:
            yield
        finally:
            sys.stdout = saved_stdout
        return

    try:
        yield
    finally:
        with suppress(Exception):
            sys.stdout.flush()
        try:
            os.dup2(saved_stdout_fd, 1)
        finally:
            os.close(saved_stdout_fd)
            sys.stdout = saved_stdout
