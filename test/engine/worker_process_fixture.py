"""Real-process fixtures for the worker primitive tests."""

import json
import subprocess
import sys
import time
from pathlib import Path

from chipcompiler.engine.worker import spawn, worker_main


def _handler(payload, result, flush):
    mode = payload["mode"]
    if mode == "segfault":
        import ctypes

        ctypes.string_at(0)
    if mode == "echo":
        Path(payload["observed_path"]).write_text(json.dumps(payload), encoding="utf-8")
        return True
    if mode == "tree":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        Path(payload["child_pid_path"]).write_text(str(child.pid), encoding="utf-8")
        Path(payload["ready_path"]).write_text("ready", encoding="utf-8")
        time.sleep(60)
    if mode == "parent_death":
        Path(payload["ready_path"]).write_text("ready", encoding="utf-8")
        time.sleep(60)
    if mode == "flush":
        result["events"].append({"type": "started"})
        flush()
        return True
    return False


def _parent() -> None:
    payload = json.loads(sys.stdin.read())
    process = spawn(
        "test.engine.worker_process_fixture",
        {"attempt_id": "parent-death-test", "mode": "parent_death", **payload},
        result_path=Path(payload["result_path"]),
        stdout=subprocess.DEVNULL,
        cwd=payload["repository"],
    )
    Path(payload["worker_pid_path"]).write_text(str(process.pid), encoding="utf-8")
    process.wait()


if __name__ == "__main__":
    if sys.argv[1:] == ["parent"]:
        _parent()
    else:
        raise SystemExit(worker_main(_handler))
