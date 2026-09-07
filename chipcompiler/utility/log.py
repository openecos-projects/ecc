#!/usr/bin/env python

import ctypes
import logging
import os
import sys
import threading
import time
from contextlib import contextmanager, suppress
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import TextIO

# ponytail: process-wide fds require one lock; move tools to subprocesses for parallel capture.
stdio_redirect_lock = threading.RLock()

_persistent_redirect: "_StdioRedirect | None" = None


def _close_persistent_redirect() -> None:
    """Close the process-wide persistent redirect if any."""
    global _persistent_redirect
    if _persistent_redirect is not None:
        prev = _persistent_redirect
        _persistent_redirect = None
        prev.close()


# TODO: Move some functions to Logger Module
def build_timestamped_log_file(log_file: str, pid: int | None = None) -> str:
    """
    Build a timestamped log file path from a base path.
    Example:
      /tmp/chipcompiler-api-server.log
      -> /tmp/chipcompiler-api-server-20260211-090428-12345.log
    """
    resolved_path = os.path.abspath(os.path.expanduser(log_file))
    base_dir = os.path.dirname(resolved_path) or "."
    base_name = os.path.basename(resolved_path)
    stem, ext = os.path.splitext(base_name)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    pid_value = os.getpid() if pid is None else pid

    file_name = f"{stem}-{timestamp}-{pid_value}{ext}" if ext else f"{stem}-{timestamp}-{pid_value}"

    return os.path.join(base_dir, file_name)


def rotate_log_on_start(log_file: str, max_bytes: int, backup_count: int) -> None:
    """Rotate log file at startup if it exceeds max_bytes."""
    if max_bytes <= 0 or not os.path.exists(log_file):
        return
    try:
        if os.path.getsize(log_file) < max_bytes:
            return
    except OSError:
        return

    if backup_count <= 0:
        os.remove(log_file)
        return

    # Shift existing backups: .5 -> delete, .4 -> .5, ... .1 -> .2
    oldest = f"{log_file}.{backup_count}"
    if os.path.exists(oldest):
        os.remove(oldest)
    for i in range(backup_count - 1, 0, -1):
        src, dst = f"{log_file}.{i}", f"{log_file}.{i + 1}"
        if os.path.exists(src):
            os.replace(src, dst)
    os.replace(log_file, f"{log_file}.1")


def flush_cstdio() -> None:
    """Flush C stdio buffers (printf/std::cout/glog) that Python-level flushes miss.

    C/C++ output sits in libc's user-space buffer and is written to fd 1/2 only
    on flush, so it must be drained before retargeting the fds, or the pending
    bytes land in whatever the fd points to at flush time.
    """
    with suppress(Exception):
        ctypes.CDLL(None).fflush(None)


class _StdioRedirect:
    def __init__(self, log_file: str, *, acquire_lock: bool = True, track_persistent: bool = False):
        self.log_file = log_file
        self._acquire_lock = acquire_lock
        self._track_persistent = track_persistent
        self._lock_acquired = False
        self._saved_fds: tuple[int, int] | None = None
        self._saved_streams: tuple[TextIO, TextIO] | None = None
        self._log_stream: TextIO | None = None

    def __enter__(self) -> "_StdioRedirect":
        global _persistent_redirect
        if self._acquire_lock:
            stdio_redirect_lock.acquire()
            self._lock_acquired = True
        try:
            fd1 = os.dup(1)
            try:
                fd2 = os.dup(2)
            except BaseException:
                os.close(fd1)
                raise
            self._saved_fds = (fd1, fd2)
            self._saved_streams = (sys.stdout, sys.stderr)
            self._log_stream = open(self.log_file, "a", encoding="utf-8", buffering=1)
            for stream in (sys.stdout, sys.stderr):
                with suppress(Exception):
                    stream.flush()
            flush_cstdio()
            os.dup2(self._log_stream.fileno(), 1)
            os.dup2(self._log_stream.fileno(), 2)
            sys.stdout = os.fdopen(1, "w", encoding="utf-8", buffering=1, closefd=False)
            sys.stderr = os.fdopen(2, "w", encoding="utf-8", buffering=1, closefd=False)
            if self._track_persistent:
                _persistent_redirect = self
            return self
        except BaseException:
            self._restore()
            if self._lock_acquired:
                stdio_redirect_lock.release()
                self._lock_acquired = False
            raise

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        try:
            self._restore()
        finally:
            if self._lock_acquired:
                stdio_redirect_lock.release()
                self._lock_acquired = False

    def close(self) -> None:
        self.__exit__(None, None, None)

    def flush(self) -> None:
        if self._log_stream is not None:
            self._log_stream.flush()

    def _restore(self) -> None:
        global _persistent_redirect
        if self._saved_fds is None:
            return
        if self._track_persistent and _persistent_redirect is self:
            _persistent_redirect = None
        for stream in (sys.stdout, sys.stderr):
            with suppress(Exception):
                stream.flush()
        flush_cstdio()
        with suppress(OSError):
            os.dup2(self._saved_fds[0], 1)
            os.dup2(self._saved_fds[1], 2)
            os.close(self._saved_fds[0])
            os.close(self._saved_fds[1])
        if self._saved_streams is not None:
            sys.stdout, sys.stderr = self._saved_streams
        if self._log_stream is not None:
            self._log_stream.close()
        self._saved_fds = None
        self._saved_streams = None
        self._log_stream = None


def redirect_stdio_to_file(log_file: str) -> _StdioRedirect:
    """Redirect process stdout/stderr to log_file at file-descriptor level.

    Does NOT acquire stdio_redirect_lock; callers that need serialized
    redirects should use capture_stdio_to_file() instead.
    """
    _close_persistent_redirect()
    redirect = _StdioRedirect(log_file, acquire_lock=False, track_persistent=True)
    redirect.__enter__()
    return redirect


@contextmanager
def capture_stdio_to_file(log_file: str | None):
    """Redirect fd 1/2 for one scope, then restore the original streams.

    Yields True when capture succeeded, False when setup failed (bad path,
    permissions, etc.).  Callers that need Incomplete on capture failure
    should check the flag.
    """
    if not log_file:
        yield True
        return

    redirect = _StdioRedirect(log_file)
    try:
        redirect.__enter__()
    except Exception:
        yield False
        return
    try:
        yield True
    finally:
        with suppress(Exception):
            redirect.__exit__(None, None, None)


def init_api_runtime_log(
    log_file: str,
    max_bytes: int = 20 * 1024 * 1024,
    backup_count: int = 5,
) -> str:
    """Initialize API runtime logging: rotate if needed, redirect stdio."""
    resolved = os.path.abspath(os.path.expanduser(log_file))
    os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
    rotate_log_on_start(resolved, max_bytes, backup_count)
    redirect_stdio_to_file(resolved)
    return resolved


class Logger:
    def __init__(
        self,
        name: str = "ecc",
        log_file: str | None = None,
        log_dir: str | None = None,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5,
        level: int = logging.INFO,
        console_level: int | None = None,
        file_level: int | None = None,
        fmt: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    ):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        self.logger.propagate = False

        if not self.logger.handlers:
            formatter = logging.Formatter(fmt)

            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            console_handler.setLevel(logging.WARNING if console_level is None else console_level)
            self.logger.addHandler(console_handler)

            if log_file or log_dir:
                file = (
                    log_file
                    if log_file
                    else f"{log_dir}/{name}.{time.strftime('%Y-%m-%d_%H-%M-%S')}"
                )
                file_handler = RotatingFileHandler(
                    file, maxBytes=max_bytes, backupCount=backup_count
                )
                file_handler.setFormatter(formatter)
                file_handler.setLevel(level if file_level is None else file_level)
                self.logger.addHandler(file_handler)

    def debug(self, msg: str, *args, **kwargs):
        self.logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        self.logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        self.logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        self.logger.error(msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs):
        self.logger.exception(msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs):
        self.logger.critical(msg, *args, **kwargs)

    def log_separator(self, max_len=60):
        self.logger.info("#" * max_len)

    def log_section(self, section: str, max_len=60):
        if len(section) >= max_len:
            section = section[:max_len]
        self.logger.info("")
        self.logger.info("#" * max_len)
        padding = (max_len - len(section)) // 2
        self.logger.info(" " * padding + section + " " * padding)
        self.logger.info("#" * max_len)
        self.logger.info("")

    def write_to_file(self, path: str, msg: str) -> None:
        """Append a formatted message directly to *path*, bypassing handlers."""
        record = self.logger.makeRecord(self.logger.name, logging.INFO, "", 0, msg, (), None)
        formatter = self.logger.handlers[0].formatter if self.logger.handlers else None
        text = formatter.format(record) if formatter else msg
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def create_logger(
    name: str = "ecc",
    log_file: str | None = None,
    log_dir: str | None = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    level: int = logging.INFO,
    console_level: int | None = None,
    file_level: int | None = None,
    fmt: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
) -> Logger:
    if log_file is not None and os.path.exists(log_file):
        return Logger(
            name=name,
            log_file=log_file,
            max_bytes=max_bytes,
            backup_count=backup_count,
            level=level,
            console_level=console_level,
            file_level=file_level,
            fmt=fmt,
        )
    elif log_dir is not None and os.path.exists(log_dir):
        return Logger(
            name=name,
            log_dir=log_dir,
            max_bytes=max_bytes,
            backup_count=backup_count,
            level=level,
            console_level=console_level,
            file_level=file_level,
            fmt=fmt,
        )
    else:
        return Logger(
            name=name,
            log_file=None,
            max_bytes=max_bytes,
            backup_count=backup_count,
            level=level,
            console_level=console_level,
            file_level=file_level,
            fmt=fmt,
        )
