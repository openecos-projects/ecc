import json
import os
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

import pytest

from ecc_experience.command_receipts import load_request, prepare_request, read_receipt
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.process import CliRunner, cli_prefix


def test_durable_public_command_writes_completion_and_does_not_repeat(tmp_path):
    deadline = time.monotonic() + 30
    prepared = []
    result = CliRunner(tmp_path, deadline, durable_receipts=True).invoke(
        ["init", str(tmp_path / "project"), "--design-name", "sample", "--plain"],
        deadline=deadline,
        on_prepared=prepared.append,
    )
    request = load_request(Path(prepared[0]["request"]))
    receipt = read_receipt(request, prepared[0]["request_fingerprint"])
    assert result.exit_code == 0, result.stderr.read_text()
    assert receipt["status"] == "complete"
    assert receipt["process_tree_quiescent"] is True
    assert receipt["exit_code"] == 0
    before = request.receipt.read_bytes()
    repeated = subprocess.run(
        [*cli_prefix(), "_experience-command-worker", str(request.path)], capture_output=True
    )
    assert repeated.returncode == 2
    assert request.receipt.read_bytes() == before


def test_receipt_waits_for_orphan_in_separate_session(tmp_path):
    request = prepare_request(tmp_path / "command-0001", ["status", "--json"])
    marker = tmp_path / "child-finished"
    orphan_code = (
        "import time; from pathlib import Path; time.sleep(0.8); "
        f"Path({str(marker)!r}).write_text('done')"
    )
    cli_code = (
        "import subprocess,sys; "
        f"subprocess.Popen([sys.executable,'-c',{orphan_code!r}],start_new_session=True)"
    )
    worker_code = (
        "import sys; from pathlib import Path; from ecc_experience import command_worker; "
        f"command_worker.cli_prefix=lambda:[sys.executable,'-c',{cli_code!r}]; "
        f"raise SystemExit(command_worker.execute(Path({str(request.path)!r})))"
    )
    process = subprocess.Popen([sys.executable, "-c", worker_code])
    try:
        deadline = time.monotonic() + 10
        while not request.receipt.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        receipt = read_receipt(request, request.fingerprint)
        assert receipt["status"] == "running"
        assert not marker.exists()
        assert process.wait(timeout=10) == 0
        receipt = read_receipt(request, request.fingerprint)
        assert marker.read_text() == "done"
        assert receipt["process_tree_quiescent"] is True
        assert receipt["orphan_exit_codes"] == [0]
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


@pytest.mark.parametrize(
    "arguments", [["_experience-command-worker", "x"], ["experience", "optimize"], ["run", "\0"]]
)
def test_rejects_recursive_or_invalid_commands(tmp_path, arguments):
    with pytest.raises(ExperienceError):
        prepare_request(tmp_path / "command-0001", arguments)


def test_request_and_receipt_cannot_be_replayed_or_redirected(tmp_path):
    request = prepare_request(tmp_path / "command-0001", ["status"])
    payload = json.loads(request.path.read_text())
    payload["token"] = "0" * 32
    request.path.write_text(json.dumps(payload))
    with pytest.raises(ExperienceError) as caught:
        read_receipt(load_request(request.path), request.fingerprint)
    assert caught.value.code == "experience_source_changed"
    request.receipt.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(ExperienceError):
        load_request(request.path)


def test_cancelled_command_stops_separate_session_descendant(tmp_path, monkeypatch):
    child_pid = tmp_path / "child.pid"
    child_code = "import time; time.sleep(60)"
    command = (
        "import subprocess,sys,time; from pathlib import Path; "
        f"child=subprocess.Popen([sys.executable,'-c',{child_code!r}],start_new_session=True); "
        f"Path({str(child_pid)!r}).write_text(str(child.pid)); time.sleep(60)"
    )
    process = subprocess.Popen([sys.executable, "-c", command], start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while not child_pid.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        pid = int(child_pid.read_text())
        CliRunner._stop(process, cooperative=False)
        stat = Path(f"/proc/{pid}/stat")
        with suppress(FileNotFoundError, ProcessLookupError):
            assert stat.read_text().split()[2] == "Z"
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        if child_pid.exists():
            with suppress(ProcessLookupError):
                os.kill(int(child_pid.read_text()), 9)
