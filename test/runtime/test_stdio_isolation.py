"""Tests for chipcompiler.runtime.stdio_isolation."""

import os
import sys

import pytest

from chipcompiler.runtime.stdio_isolation import StdioIsolation


class TestStdioIsolation:
    def test_not_installed_raises(self):
        iso = StdioIsolation()
        with pytest.raises(RuntimeError, match="not installed"):
            _ = iso.protocol_stream

    def test_install_returns_writable_stream(self):
        iso = StdioIsolation()
        saved_stdout_fd = os.dup(1)
        saved_stderr_fd = os.dup(2)
        saved_stdout = sys.stdout
        try:
            r_fd, w_fd = os.pipe()
            os.dup2(w_fd, 1)
            os.close(w_fd)

            r2_fd, w2_fd = os.pipe()
            os.dup2(w2_fd, 2)
            os.close(w2_fd)

            stream = iso.install()
            assert iso.installed

            stream.write(b"protocol data")
            stream.flush()

            os.write(1, b"tool output on fd1")

            os.dup2(saved_stdout_fd, 1)
            os.dup2(saved_stderr_fd, 2)
            sys.stdout = saved_stdout

            protocol_data = os.read(r_fd, 4096)
            stderr_data = os.read(r2_fd, 4096)

            assert protocol_data == b"protocol data"
            assert b"tool output on fd1" in stderr_data

            iso.close()
            os.close(r_fd)
            os.close(r2_fd)
        finally:
            os.dup2(saved_stdout_fd, 1)
            os.dup2(saved_stderr_fd, 2)
            sys.stdout = saved_stdout
            os.close(saved_stdout_fd)
            os.close(saved_stderr_fd)

    def test_double_install_is_idempotent(self):
        iso = StdioIsolation()
        saved_stdout_fd = os.dup(1)
        saved_stderr_fd = os.dup(2)
        saved_stdout = sys.stdout
        try:
            r_fd, w_fd = os.pipe()
            os.dup2(w_fd, 1)
            os.close(w_fd)
            r2_fd, w2_fd = os.pipe()
            os.dup2(w2_fd, 2)
            os.close(w2_fd)

            s1 = iso.install()
            s2 = iso.install()
            assert s1 is s2

            iso.close()
            os.close(r_fd)
            os.close(r2_fd)
        finally:
            os.dup2(saved_stdout_fd, 1)
            os.dup2(saved_stderr_fd, 2)
            sys.stdout = saved_stdout
            os.close(saved_stdout_fd)
            os.close(saved_stderr_fd)
