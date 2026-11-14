"""The workspace logger keeps its console output off stdout (#433)."""

import logging
import uuid

import pytest

from chipcompiler.utility.log import Logger, create_logger


@pytest.fixture
def logger_name():
    """A logger name of its own: handlers are attached once per name and process."""
    name = f"log-test-{uuid.uuid4().hex}"
    yield name
    logger = logging.getLogger(name)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def test_console_warnings_go_to_stderr(capsys, logger_name):
    logger = Logger(name=logger_name)

    logger.info("below the console level")
    logger.warning("step finished with a note")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "WARNING - step finished with a note" in captured.err
    assert "below the console level" not in captured.err


def test_log_file_receives_every_level(capsys, tmp_path, logger_name):
    logger = create_logger(name=logger_name, log_dir=tmp_path)

    logger.info("kept in the file")
    logger.warning("on the console as well")

    (log_file,) = tmp_path.iterdir()
    text = log_file.read_text()
    assert "INFO - kept in the file" in text
    assert "WARNING - on the console as well" in text
    assert capsys.readouterr().out == ""
