#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import os
import sys
from datetime import datetime
from typing import TextIO


API_RUNTIME_LOG_ENV_KEY = "CHIPCOMPILER_API_SERVER_LOG_FILE"

_runtime_log_stream: TextIO | None = None


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

    if ext:
        file_name = f"{stem}-{timestamp}-{pid_value}{ext}"
    else:
        file_name = f"{stem}-{timestamp}-{pid_value}"

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


def redirect_stdio_to_file(log_file: str) -> TextIO:
    """Redirect process stdout/stderr to log_file at file-descriptor level."""
    log_stream = open(log_file, "a", encoding="utf-8", buffering=1)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass

    os.dup2(log_stream.fileno(), 1)
    os.dup2(log_stream.fileno(), 2)
    sys.stdout = os.fdopen(1, "w", encoding="utf-8", buffering=1, closefd=False)
    sys.stderr = os.fdopen(2, "w", encoding="utf-8", buffering=1, closefd=False)
    return log_stream


def init_api_runtime_log(
    log_file: str,
    max_bytes: int = 20 * 1024 * 1024,
    backup_count: int = 5,
) -> str:
    """Initialize API runtime logging: rotate if needed, redirect stdio."""
    global _runtime_log_stream

    resolved = os.path.abspath(os.path.expanduser(log_file))
    os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
    rotate_log_on_start(resolved, max_bytes, backup_count)
    _runtime_log_stream = redirect_stdio_to_file(resolved)
    return resolved


def get_api_log_file_from_env() -> str | None:
    """
    Get runtime log file path from environment.
    """
    value = os.environ.get(API_RUNTIME_LOG_ENV_KEY, "").strip()
    return value or None
