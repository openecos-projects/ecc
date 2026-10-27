import io
import json
import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.engine import worker

_REPOSITORY = Path(__file__).parents[2]
_FIXTURE_MODULE = "test.engine.worker_process_fixture"


def _spawn_fixture(tmp_path, mode, **payload):
    result_path = tmp_path / "worker-result.json"
    process = worker.spawn(
        _FIXTURE_MODULE,
        {"attempt_id": "test-attempt", "mode": mode, **payload},
        result_path=result_path,
        stdout=subprocess.DEVNULL,
        cwd=str(_REPOSITORY),
    )
    return process, result_path


def _wait_for_file(path: Path) -> None:
    deadline = time.monotonic() + 10
    while not path.is_file() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert path.is_file(), f"timed out waiting for {path}"


def _process_state(pid: int) -> str | None:
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(")", 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        return None


def _wait_for_process_death(pid: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if _process_state(pid) in {None, "Z"}:
            return
        time.sleep(0.01)
    assert _process_state(pid) in {None, "Z"}


def _stop_process(process: subprocess.Popen) -> None:
    worker.terminate_process_group(process)


def test_worker_command_selects_source_and_frozen_dispatch(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert worker.worker_command("chipcompiler.engine.step_subprocess") == [
        sys.executable,
        "-m",
        "chipcompiler.engine.step_subprocess",
    ]

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert worker.worker_command("chipcompiler.engine.step_subprocess") == [
        sys.executable,
        "--ecc-worker",
        "chipcompiler.engine.step_subprocess",
    ]


def test_spawn_replaces_stale_result_and_supplies_payload(tmp_path):
    result_path = tmp_path / "worker-result.json"
    result_path.write_text('{"done": true, "ok": true}', encoding="utf-8")
    observed_path = tmp_path / "observed.json"

    process, _ = _spawn_fixture(tmp_path, "echo", observed_path=str(observed_path))
    try:
        assert process.wait(timeout=10) == 0
    finally:
        _stop_process(process)

    observed = json.loads(observed_path.read_text(encoding="utf-8"))
    assert observed == {
        "attempt_id": "test-attempt",
        "mode": "echo",
        "observed_path": str(observed_path),
        "result_path": str(result_path),
        "parent_pid": os.getpid(),
    }
    assert worker.read_result(result_path) == {
        "attempt_id": "test-attempt",
        "ok": True,
        "done": True,
        "error": None,
        "events": [],
    }


def test_spawn_stdin_failure_terminates_started_process(monkeypatch, tmp_path):
    class BrokenStdin(io.BytesIO):
        def write(self, _data):
            raise BrokenPipeError("worker closed stdin")

    process = SimpleNamespace(pid=4321, stdin=BrokenStdin())
    monkeypatch.setattr(worker.subprocess, "Popen", lambda *_args, **_kwargs: process)
    terminated = []
    monkeypatch.setattr(worker, "terminate_process_group", terminated.append)

    with pytest.raises(BrokenPipeError, match="worker closed stdin"):
        worker.spawn("unused.module", {}, result_path=tmp_path / "result.json")

    assert terminated == [process]


def test_spawn_resolves_relative_result_path_before_changing_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    child_cwd = tmp_path / "child"
    child_cwd.mkdir()
    result_path = Path("result.json")
    observed_path = tmp_path / "observed.json"

    process = worker.spawn(
        _FIXTURE_MODULE,
        {"attempt_id": "test-attempt", "mode": "echo", "observed_path": str(observed_path)},
        result_path=result_path,
        stdout=subprocess.DEVNULL,
        cwd=str(child_cwd),
    )
    try:
        assert process.wait(timeout=10) == 0
    finally:
        _stop_process(process)

    observed = json.loads(observed_path.read_text(encoding="utf-8"))
    assert observed["result_path"] == str(tmp_path / "result.json")
    assert worker.read_result(result_path) == {
        "attempt_id": "test-attempt",
        "ok": True,
        "done": True,
        "error": None,
        "events": [],
    }
    assert not (child_cwd / "result.json").exists()


def test_worker_main_echoes_attempt_id_on_every_flush(monkeypatch, tmp_path):
    result_path = tmp_path / "result.json"
    payload = {
        "attempt_id": "test-attempt",
        "parent_pid": os.getpid(),
        "result_path": str(result_path),
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(worker, "arm_parent_death_signal", lambda _pid: None)
    monkeypatch.setattr(worker, "_start_parent_death_watchdog", lambda: None)
    writes = []
    write_atomic = worker.write_result_atomic

    def record_write(path, result):
        writes.append(dict(result))
        write_atomic(path, result)

    monkeypatch.setattr(worker, "write_result_atomic", record_write)

    def handler(_payload, result, flush):
        result["events"].append({"type": "started"})
        flush()
        result["events"].append({"type": "finished"})
        return True

    assert worker.worker_main(handler) == 0
    assert [write["attempt_id"] for write in writes] == ["test-attempt", "test-attempt"]
    assert worker.read_result(result_path) == {
        "attempt_id": "test-attempt",
        "ok": True,
        "done": True,
        "error": None,
        "events": [{"type": "started"}, {"type": "finished"}],
    }


def test_atomic_result_reader_never_observes_partial_json(tmp_path):
    result_path = tmp_path / "result.json"
    values = [
        {"attempt_id": "first", "done": False, "events": ["start"]},
        {"attempt_id": "second", "done": True, "ok": True, "events": []},
    ]
    finished = threading.Event()
    errors = []

    def write_results():
        for index in range(200):
            worker.write_result_atomic(result_path, values[index % 2])
        finished.set()

    def read_results():
        while not finished.is_set():
            try:
                value = json.loads(result_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                continue
            except Exception as exc:
                errors.append(exc)
                return
            if value not in values:
                errors.append(AssertionError(value))
                return

    writer = threading.Thread(target=write_results)
    reader = threading.Thread(target=read_results)
    writer.start()
    reader.start()
    writer.join(timeout=10)
    reader.join(timeout=10)

    assert not writer.is_alive()
    assert not reader.is_alive()
    assert errors == []


@pytest.mark.skipif(sys.platform != "linux", reason="Linux signal semantics required")
def test_real_worker_segfault_is_visible_to_caller(tmp_path):
    process, result_path = _spawn_fixture(tmp_path, "segfault")
    try:
        assert worker.poll_until_exit(process, result_path=result_path) == -signal.SIGSEGV
        assert worker.read_result(result_path) is None
    finally:
        _stop_process(process)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux process groups required")
def test_cancel_exception_escapes_and_caller_stops_process_tree(tmp_path):
    child_pid_path = tmp_path / "child.pid"
    ready_path = tmp_path / "ready"
    process, result_path = _spawn_fixture(
        tmp_path,
        "tree",
        child_pid_path=str(child_pid_path),
        ready_path=str(ready_path),
    )
    _wait_for_file(ready_path)
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    cancelled = RuntimeError("cancel requested")

    def cancel():
        raise cancelled

    try:
        with pytest.raises(RuntimeError) as caught:
            worker.poll_until_exit(process, result_path=result_path, cancel=cancel)
        assert caught.value is cancelled
    finally:
        _stop_process(process)

    _wait_for_process_death(child_pid)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux parent-death signal required")
@pytest.mark.parametrize("mode", ["parent_death", "tree"])
def test_worker_dies_when_parent_is_killed_after_arming(tmp_path, mode):
    ready_path = tmp_path / "ready"
    worker_pid_path = tmp_path / "worker.pid"
    parent = subprocess.Popen(
        [sys.executable, "-m", _FIXTURE_MODULE, "parent"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        cwd=_REPOSITORY,
        start_new_session=True,
    )
    worker_pid = None
    child_pid = None
    child_pid_path = tmp_path / "child.pid"
    try:
        assert parent.stdin is not None
        with parent.stdin:
            parent.stdin.write(
                json.dumps(
                    {
                        "mode": mode,
                        "ready_path": str(ready_path),
                        "child_pid_path": str(child_pid_path),
                        "worker_pid_path": str(worker_pid_path),
                        "result_path": str(tmp_path / "worker-result.json"),
                        "repository": str(_REPOSITORY),
                    }
                ).encode("utf-8")
            )
        _wait_for_file(worker_pid_path)
        _wait_for_file(ready_path)
        worker_pid = int(worker_pid_path.read_text(encoding="utf-8"))
        if mode == "tree":
            _wait_for_file(child_pid_path)
            child_pid = int(child_pid_path.read_text(encoding="utf-8"))

        os.kill(parent.pid, signal.SIGKILL)
        assert parent.wait(timeout=10) == -signal.SIGKILL
        _wait_for_process_death(worker_pid)
        if child_pid is not None:
            _wait_for_process_death(child_pid)
    finally:
        if parent.poll() is None:
            parent.kill()
        parent.wait()
        if worker_pid is not None:
            with suppress(ProcessLookupError):
                os.kill(worker_pid, signal.SIGKILL)
        if child_pid is not None:
            with suppress(ProcessLookupError):
                os.kill(child_pid, signal.SIGKILL)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux process groups required")
def test_group_termination_includes_descendant_of_exited_leader(tmp_path):
    child_pid_path = tmp_path / "child.pid"
    ready_path = tmp_path / "ready"
    descendant = (
        "import signal,time,pathlib,sys; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "pathlib.Path(sys.argv[1]).write_text('ready'); time.sleep(60)"
    )
    leader_script = (
        "import subprocess,sys,pathlib; "
        "child=subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); "
        "pathlib.Path(sys.argv[3]).write_text(str(child.pid))"
    )
    leader = subprocess.Popen(
        [sys.executable, "-c", leader_script, descendant, str(ready_path), str(child_pid_path)],
        start_new_session=True,
    )
    child_pid = None
    try:
        assert leader.wait(timeout=10) == 0
        _wait_for_file(ready_path)
        child_pid = int(child_pid_path.read_text(encoding="utf-8"))

        worker.terminate_process_group(leader)

        _wait_for_process_death(child_pid)
    finally:
        if child_pid is not None:
            with suppress(ProcessLookupError):
                os.kill(child_pid, signal.SIGKILL)
        if leader.poll() is None:
            worker.terminate_process_group(leader)
