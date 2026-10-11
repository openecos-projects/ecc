import io
import json
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.engine import step_subprocess
from chipcompiler.engine.step_execution import execute_tool_step


@pytest.fixture(autouse=True)
def _no_parent_death_signal(monkeypatch):
    # main() runs in the pytest process here; arming PR_SET_PDEATHSIG would
    # SIGKILL the runner when the recorded parent pid is not our ppid.
    monkeypatch.setattr(step_subprocess, "_arm_parent_death_signal", lambda parent_pid: None)


def _workspace_step(tmp_path, name="place", tool="ecc"):
    log_file = tmp_path / "log" / "step.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        name=name,
        tool=tool,
        directory=str(tmp_path),
        log=SimpleNamespace(file=str(log_file)),
    )


def _workspace(tmp_path):
    return SimpleNamespace(directory=str(tmp_path), logger=logging.getLogger("ecc-test"))


class _FakeStdin(io.BytesIO):
    def close(self):
        # keep the buffer readable so tests can assert the payload
        pass


class _FakePopen:
    """Minimal subprocess.Popen stand-in driven by a poll script."""

    def __init__(self, returncode=0, poll_script=None):
        self.pid = 4321
        self.returncode = None
        self.stdin = _FakeStdin()
        self._returncode = returncode
        self._poll_script = list(poll_script) if poll_script is not None else [None]
        self.terminated = False
        self.killed = False

    def poll(self):
        if self.returncode is not None:
            return self.returncode
        value = self._poll_script.pop(0) if self._poll_script else self._returncode
        if value is not None:
            self.returncode = value
        return value

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = self._returncode
        return self.returncode


def test_is_enabled_env_switch(monkeypatch):
    monkeypatch.delenv("ECC_STEP_SUBPROCESS", raising=False)
    assert step_subprocess.is_enabled()
    monkeypatch.setenv("ECC_STEP_SUBPROCESS", "1")
    assert step_subprocess.is_enabled()
    monkeypatch.setenv("ECC_STEP_SUBPROCESS", "0")
    assert not step_subprocess.is_enabled()


def test_execute_step_subprocess_reports_worker_crash(monkeypatch, tmp_path):
    monkeypatch.setenv(step_subprocess._ENABLED_ENV, "1")
    fake = _FakePopen(returncode=-11)
    monkeypatch.setattr(step_subprocess.subprocess, "Popen", lambda *a, **k: fake)
    step = _workspace_step(tmp_path)
    result = execute_tool_step(_workspace(tmp_path), step, None)

    payload = json.loads(fake.stdin.getvalue())
    assert payload["step_name"] == "place"
    assert payload["tool"] == "ecc"
    assert payload["result_path"].endswith(step_subprocess._RESULT_NAME)
    assert result.error is not None
    assert "code -11" in result.error


def test_execute_step_subprocess_reports_worker_failure_result(monkeypatch, tmp_path):
    monkeypatch.setenv(step_subprocess._ENABLED_ENV, "1")
    step = _workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    result_path.write_text(
        json.dumps({"done": True, "ok": False, "error": "boom", "events": []}),
        encoding="utf-8",
    )
    fake = _FakePopen(returncode=1)
    monkeypatch.setattr(step_subprocess.subprocess, "Popen", lambda *a, **k: fake)
    result = execute_tool_step(_workspace(tmp_path), step, None)

    assert result.error is not None
    assert "boom" in result.error


def test_execute_step_subprocess_succeeds_and_replays_events(monkeypatch, tmp_path):
    monkeypatch.setenv(step_subprocess._ENABLED_ENV, "1")
    step = _workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    result_path.write_text(
        json.dumps(
            {
                "done": True,
                "ok": True,
                "error": None,
                "events": [
                    {"type": "subflow_stage", "subflow_step": {"name": "load", "state": "Ongoing"}},
                    {"type": "subflow_stage", "subflow_step": {"name": "load", "state": "Success"}},
                ],
            }
        ),
        encoding="utf-8",
    )
    fake = _FakePopen(returncode=0)
    monkeypatch.setattr(step_subprocess.subprocess, "Popen", lambda *a, **k: fake)

    replayed = []

    class Observer:
        def on_subflow_stage(self, workspace_step, subflow_step):
            replayed.append((workspace_step.name, subflow_step))

        def raise_if_cancelled(self):
            return None

    result = execute_tool_step(_workspace(tmp_path), step, None, observer=Observer())

    assert result.error is None
    assert [entry[1]["state"] for entry in replayed] == ["Ongoing", "Success"]


def test_execute_step_subprocess_cancel_terminates_worker(monkeypatch, tmp_path):
    monkeypatch.setenv(step_subprocess._ENABLED_ENV, "1")
    fake = _FakePopen(returncode=0, poll_script=[None, None, None])
    monkeypatch.setattr(step_subprocess.subprocess, "Popen", lambda *a, **k: fake)

    class Cancelled(RuntimeError):
        pass

    class Observer:
        calls = 0

        def raise_if_cancelled(self):
            Observer.calls += 1
            if Observer.calls >= 2:
                raise Cancelled("stop")

    step = _workspace_step(tmp_path)
    result = execute_tool_step(_workspace(tmp_path), step, None, observer=Observer())

    assert fake.terminated
    assert result.error is not None
    assert "cancelled" in result.error


def test_execute_tool_step_falls_back_in_process(monkeypatch, tmp_path):
    monkeypatch.setenv("ECC_STEP_SUBPROCESS", "0")
    dispatched = []
    monkeypatch.setattr(
        step_subprocess,
        "execute_step_subprocess",
        lambda *a, **k: dispatched.append(a),
    )
    ran = []
    monkeypatch.setattr(
        "chipcompiler.tools.run_step",
        lambda **kwargs: ran.append(kwargs) or True,
    )
    step = _workspace_step(tmp_path)
    engine_db = SimpleNamespace(engine=object(), initialization_error=None)
    result = execute_tool_step(_workspace(tmp_path), step, engine_db)

    assert dispatched == []
    assert ran and result.error is None


class _FakeFlow:
    engine_db = SimpleNamespace(initialization_error=None, engine=None)

    def __init__(self, workspace):
        self.workspace = workspace
        self.initialized_for = None

    def create_step_workspaces(self, *, initialize_config=True):
        assert initialize_config is False

    def get_workspace_step(self, name):
        return self._step if name == self._step.name else None

    def init_db_engine_for_step(self, step):
        self.initialized_for = step
        return True


def _patch_worker_dependencies(monkeypatch, tmp_path, step, flow, run_step):
    monkeypatch.setattr("chipcompiler.data.load_workspace", lambda directory: _workspace(tmp_path))
    monkeypatch.setattr("chipcompiler.engine.flow.EngineFlow", lambda workspace: flow)
    monkeypatch.setattr("chipcompiler.tools.run_step", run_step)


def _payload_stream(tmp_path, step, result_path):
    payload = {
        "schema_version": 1,
        "workspace_directory": str(tmp_path),
        "step_name": step.name,
        "tool": step.tool,
        "result_path": str(result_path),
        "parent_pid": os.getpid(),
    }
    return io.StringIO(json.dumps(payload))


def test_worker_main_success_writes_result(monkeypatch, tmp_path):
    step = _workspace_step(tmp_path)
    result_path = tmp_path / "out" / "result.json"
    flow = _FakeFlow(_workspace(tmp_path))
    flow._step = step
    events = []

    def fake_run_step(workspace, step, ecc_module=None):
        workspace._runtime_flow_observer.on_subflow_stage(
            step, {"name": "load", "state": "Ongoing"}
        )
        events.append("ran")
        return True

    _patch_worker_dependencies(monkeypatch, tmp_path, step, flow, fake_run_step)
    monkeypatch.setattr(sys, "stdin", _payload_stream(tmp_path, step, result_path))

    assert step_subprocess.main() == 0
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["done"] is True
    assert result["ok"] is True
    assert result["error"] is None
    assert result["events"] == [
        {"type": "subflow_stage", "subflow_step": {"name": "load", "state": "Ongoing"}}
    ]
    assert events == ["ran"]
    assert flow.initialized_for is step


def test_worker_main_records_step_failure(monkeypatch, tmp_path):
    step = _workspace_step(tmp_path)
    result_path = tmp_path / "out" / "result.json"
    flow = _FakeFlow(_workspace(tmp_path))
    flow._step = step

    _patch_worker_dependencies(monkeypatch, tmp_path, step, flow, lambda *a, **k: False)
    monkeypatch.setattr(sys, "stdin", _payload_stream(tmp_path, step, result_path))

    assert step_subprocess.main() == 1
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["done"] is True
    assert result["ok"] is False
    assert "reported failure" in result["error"]


def test_worker_main_records_missing_step(monkeypatch, tmp_path):
    step = _workspace_step(tmp_path)
    result_path = tmp_path / "out" / "result.json"
    flow = _FakeFlow(_workspace(tmp_path))
    flow._step = SimpleNamespace(name="other", tool="ecc")

    _patch_worker_dependencies(monkeypatch, tmp_path, step, flow, lambda *a, **k: True)
    monkeypatch.setattr(sys, "stdin", _payload_stream(tmp_path, step, result_path))

    assert step_subprocess.main() == 1
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["done"] is True
    assert "missing in worker" in result["error"]


def test_worker_main_records_exceptions(monkeypatch, tmp_path):
    step = _workspace_step(tmp_path)
    result_path = tmp_path / "out" / "result.json"

    def broken_loader(directory):
        raise OSError("no workspace")

    monkeypatch.setattr("chipcompiler.data.load_workspace", broken_loader)
    monkeypatch.setattr(sys, "stdin", _payload_stream(tmp_path, step, result_path))

    assert step_subprocess.main() == 1
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["done"] is True
    assert result["ok"] is False
    assert "OSError" in result["error"]
