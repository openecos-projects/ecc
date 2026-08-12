#!/usr/bin/env python

import ctypes
import logging
import os
import sys
import time
from contextlib import suppress
from logging.handlers import RotatingFileHandler
from typing import TextIO


# TODO: Move some functions to Logger Module
def flush_cstdio() -> None:
    """Flush C stdio buffers (printf/std::cout/glog) that Python-level flushes miss.

    C/C++ output sits in libc's user-space buffer and is written to fd 1/2 only
    on flush, so it must be drained before retargeting the fds, or the pending
    bytes land in whatever the fd points to at flush time.
    """
    with suppress(Exception):
        ctypes.CDLL(None).fflush(None)


def redirect_stdio_to_file(log_file: str) -> TextIO:
    """Redirect process stdout/stderr to log_file at file-descriptor level."""
    # The stream intentionally stays open: its fd is dup2'd onto stdout/stderr below.
    log_stream = open(log_file, "a", encoding="utf-8", buffering=1)  # noqa: SIM115

    for stream in (sys.stdout, sys.stderr):
        with suppress(Exception):
            stream.flush()
    flush_cstdio()

    os.dup2(log_stream.fileno(), 1)
    os.dup2(log_stream.fileno(), 2)
    sys.stdout = os.fdopen(1, "w", encoding="utf-8", buffering=1, closefd=False)
    sys.stderr = os.fdopen(2, "w", encoding="utf-8", buffering=1, closefd=False)
    return log_stream


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
