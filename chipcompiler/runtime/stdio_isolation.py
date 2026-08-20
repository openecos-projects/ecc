"""Permanent stdio isolation for the worker process.

At worker startup, the protocol output stream is duplicated to a safe fd,
then fd 1 is permanently redirected to fd 2. This ensures that any Python,
C/C++, glog, or subprocess output goes to stderr (the log stream), while
the protocol writer uses only the saved fd for RPC frames.
"""

import os
import sys
from typing import BinaryIO


class StdioIsolation:
    """Installs permanent fd-level stdio isolation for the worker process.

    After install():
    - protocol_stream: a binary stream on the original stdout fd (for RPC frames only)
    - fd 1 and sys.stdout: permanently point to stderr (for tool/EDA output)
    """

    def __init__(self):
        self._protocol_stream: BinaryIO | None = None
        self._installed = False

    @property
    def protocol_stream(self) -> BinaryIO:
        if self._protocol_stream is None:
            raise RuntimeError("stdio isolation not installed")
        return self._protocol_stream

    @property
    def installed(self) -> bool:
        return self._installed

    def install(self) -> BinaryIO:
        """Install permanent stdio isolation. Must be called once at worker startup."""
        if self._installed:
            return self._protocol_stream  # type: ignore[return-value]

        sys.stdout.flush()
        sys.stderr.flush()

        protocol_fd = os.dup(1)
        os.dup2(2, 1)
        sys.stdout = sys.stderr

        self._protocol_stream = os.fdopen(protocol_fd, "wb", buffering=0)
        self._installed = True
        return self._protocol_stream

    def close(self) -> None:
        if self._protocol_stream is not None:
            self._protocol_stream.close()
            self._protocol_stream = None
