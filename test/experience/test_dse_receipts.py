import time

import pytest

from ecc_experience.dse.receipts import recover_command
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.process import CliRunner


def test_completed_public_command_is_recoverable_without_reexecution(tmp_path):
    arguments = ["init", str(tmp_path / "project"), "--design-name", "example", "--plain"]
    deadline = time.monotonic() + 30
    command = {"status": "running"}
    result = CliRunner(tmp_path, deadline, durable_receipts=True).invoke(
        arguments, deadline=deadline, on_prepared=command.update
    )
    assert result.exit_code == 0
    before = (tmp_path / "project/project.json").read_bytes()
    recover_command(command, arguments, tmp_path)
    assert command["status"] == "complete"
    assert command["exit_code"] == 0
    assert (tmp_path / "project/project.json").read_bytes() == before
    with pytest.raises(ExperienceError, match="changed"):
        recover_command(command, ["status"], tmp_path)


def test_unproven_interrupted_command_remains_busy(tmp_path):
    with pytest.raises(ExperienceError) as caught:
        recover_command({"status": "running"}, ["run"], tmp_path)
    assert caught.value.code == "experience_workspace_busy"
