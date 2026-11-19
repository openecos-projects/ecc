import logging
from pathlib import Path

from chipcompiler.utility.log import Logger, create_logger


def _file_handlers(logger: Logger) -> list[logging.FileHandler]:
    return [
        handler for handler in logger.logger.handlers if isinstance(handler, logging.FileHandler)
    ]


def _close_handlers(logger: Logger) -> None:
    for handler in logger.logger.handlers[:]:
        logger.logger.removeHandler(handler)
        handler.close()


def test_same_design_workspaces_have_isolated_parent_logs(tmp_path: Path):
    design = "test-log-shared-design"
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    log_dir_a = workspace_a / "log"
    log_dir_b = workspace_b / "log"
    log_dir_a.mkdir(parents=True)
    log_dir_b.mkdir(parents=True)
    logger_a = create_logger(name=design, log_dir=log_dir_a, fmt="%(message)s")
    logger_b = create_logger(name=design, log_dir=log_dir_b, fmt="%(message)s")

    try:
        assert logger_a.logger is not logger_b.logger
        handler_a = _file_handlers(logger_a)
        handler_b = _file_handlers(logger_b)
        assert len(handler_a) == 1
        assert len(handler_b) == 1
        log_path_a = Path(handler_a[0].baseFilename)
        log_path_b = Path(handler_b[0].baseFilename)
        assert log_path_a.parent == log_dir_a
        assert log_path_b.parent == log_dir_b

        logger_a.info("message from workspace a")
        logger_b.info("message from workspace b")

        assert log_path_a.read_text() == "message from workspace a\n"
        assert log_path_b.read_text() == "message from workspace b\n"
    finally:
        _close_handlers(logger_a)
        _close_handlers(logger_b)


def test_same_workspace_reuses_handlers_and_recreates_them_after_cleanup(tmp_path: Path):
    design = "test-log-repeated-workspace"
    log_dir = tmp_path / "workspace" / "log"
    log_dir.mkdir(parents=True)
    first = create_logger(name=design, log_dir=log_dir, fmt="%(message)s")
    second = create_logger(name=design, log_dir=log_dir, fmt="%(message)s")

    try:
        assert first.logger is second.logger
        assert len(first.logger.handlers) == 2
        assert len(_file_handlers(first)) == 1
        log_path = Path(_file_handlers(first)[0].baseFilename)

        first.info("first message")
        second.info("second message")

        assert log_path.read_text() == "first message\nsecond message\n"

        _close_handlers(first)
        recreated = create_logger(name=design, log_dir=log_dir, fmt="%(message)s")
        assert recreated.logger is first.logger
        assert len(recreated.logger.handlers) == 2
        assert len(_file_handlers(recreated)) == 1
    finally:
        _close_handlers(first)


def test_logger_without_log_directory_keeps_name_key():
    name = "test-log-without-directory"
    logger = create_logger(name=name)

    try:
        assert logger.logger is logging.getLogger(name)
        assert logger.logger.name == name
        assert _file_handlers(logger) == []
    finally:
        _close_handlers(logger)
