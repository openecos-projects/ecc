import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

import pytest

from ecc_experience.optimization.process import CliRunner, cancellation_signals


@pytest.mark.skipif(not Path("/proc/self/task").is_dir(), reason="Linux process tree required")
def test_timeout_stops_descendants_in_an_independent_session(tmp_path, monkeypatch):
    child_pid = tmp_path / "child.pid"
    script = (
        "import subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
        "start_new_session=True); "
        f"open({str(child_pid)!r},'w').write(str(child.pid)); "
        "time.sleep(60)"
    )
    monkeypatch.setattr(
        "ecc_experience.optimization.process.cli_prefix", lambda: [sys.executable, "-c", script]
    )
    runner = CliRunner(tmp_path, time.monotonic() + 3)

    invocation = runner.invoke(["test"], deadline=time.monotonic() + 0.5)

    assert invocation.exit_code == 124
    pid = int(child_pid.read_text())
    stat = Path(f"/proc/{pid}/stat")
    with suppress(FileNotFoundError, ProcessLookupError):
        assert stat.read_text().split(")", 1)[1].split()[0] == "Z"


def test_sigterm_uses_the_cancellation_path_and_restores_handler():
    previous = signal.getsignal(signal.SIGTERM)
    with cancellation_signals(), pytest.raises(KeyboardInterrupt):
        os.kill(os.getpid(), signal.SIGTERM)
    assert signal.getsignal(signal.SIGTERM) == previous


def test_expired_budget_never_spawns(tmp_path, monkeypatch):
    def fail_spawn(*_args, **_kwargs):
        pytest.fail("Expired budget must not spawn a CLI process")

    monkeypatch.setattr(subprocess, "Popen", fail_spawn)
    runner = CliRunner(tmp_path, time.monotonic() - 1)
    assert runner.invoke(["run"], deadline=time.monotonic()).exit_code == 124


def test_runner_passes_thread_local_environment_to_child(tmp_path, monkeypatch):
    captured = {}

    class Process:
        returncode = 0

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

    def spawn(_command, **kwargs):
        captured.update(kwargs["env"])
        return Process()

    monkeypatch.setattr(subprocess, "Popen", spawn)
    runner = CliRunner(tmp_path, time.monotonic() + 5)
    runner.set_environment({"ECC_EXPERIENCE_MAX_CONCURRENT": "4"})

    assert runner.invoke(["test"], deadline=time.monotonic() + 1).exit_code == 0
    assert captured["ECC_EXPERIENCE_MAX_CONCURRENT"] == "4"
    runner.clear_environment()
    assert not hasattr(runner._environment, "values")
