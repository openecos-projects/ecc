#!/usr/bin/env python

import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler


class Logger:
    def __init__(
        self,
        name: str = "ecc",
        log_file: str | None = None,
        log_dir: str | None = None,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5,
        level: int = logging.INFO,
        fmt: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    ):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)

        if not self.logger.handlers:
            formatter = logging.Formatter(fmt)

            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
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
                self.logger.addHandler(file_handler)

    def debug(self, msg: str, *args, **kwargs):
        self.logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        self.logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        self.logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        self.logger.error(msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs):
        self.logger.critical(msg, *args, **kwargs)


def create_logger(
    name: str = "ecc",
    log_file: str | None = None,
    log_dir: str | None = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    level: int = logging.INFO,
    fmt: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
) -> Logger:
    if log_file is not None and os.path.exists(log_file):
        return Logger(
            name=name,
            log_file=log_file,
            max_bytes=max_bytes,
            backup_count=backup_count,
            level=level,
            fmt=fmt,
        )
    elif log_dir is not None and os.path.exists(log_dir):
        return Logger(
            name=name,
            log_dir=log_dir,
            max_bytes=max_bytes,
            backup_count=backup_count,
            level=level,
            fmt=fmt,
        )
    else:
        return Logger(
            name=name,
            log_file=None,
            max_bytes=max_bytes,
            backup_count=backup_count,
            level=level,
            fmt=fmt,
        )
