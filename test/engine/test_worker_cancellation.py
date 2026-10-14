import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

import pytest

from chipcompiler.engine import step_subprocess


@pytest.mark.skipif(sys.platform != "linux", reason="Linux process state required")
def test_worker_cancellation_stops_native_descendants(tmp_path, monkeypatch):
    pid_path = tmp_path / "child.pid"
    script = (
        "import subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); "
        f"open({str(pid_path)!r},'w').write(str(child.pid)); time.sleep(60)"
    )
    original_popen = subprocess.Popen

    def launch(_arguments, **options):
        return original_popen([sys.executable, "-c", script], **options)

    monkeypatch.setattr(step_subprocess.subprocess, "Popen", launch)
    with (tmp_path / "worker.log").open("wb") as log:
        worker = step_subprocess._spawn_worker(log)
        try:
            deadline = time.monotonic() + 5
            while not pid_path.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert pid_path.is_file()
            child_pid = int(pid_path.read_text())

            step_subprocess._terminate_worker(worker)

            assert worker.poll() is not None
            stat = Path(f"/proc/{child_pid}/stat")
            assert not stat.exists() or stat.read_text().split(")", 1)[1].split()[0] == "Z"
        finally:
            if worker.poll() is None:
                worker.kill()
            worker.wait()
            if pid_path.is_file():
                with suppress(ProcessLookupError):
                    os.kill(int(pid_path.read_text()), signal.SIGKILL)
