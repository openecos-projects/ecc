import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from agent import candidate_worker
from chipcompiler.runtime.operations import RuntimeOperationCancelled
from chipcompiler.runtime.workspace_api import RuntimeApiError

# Captured at import time: tests patch subprocess.Popen on the shared module,
# so fake workers must spawn through the original.
_REAL_POPEN = subprocess.Popen


def _flow(tmp_path):
    return SimpleNamespace(workspace=SimpleNamespace(directory=tmp_path))


class _StdinRecorder:
    def __init__(self):
        self.data = b""

    def write(self, chunk):
        self.data += chunk

    def close(self):
        pass


class _FakeProcess:
    """Wrap a real child process so tests can observe termination."""

    def __init__(self, argv):
        self._process = _REAL_POPEN(argv, stdin=subprocess.DEVNULL)
        self.stdin = _StdinRecorder()
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self):
        return self._process.poll()

    @property
    def returncode(self):
        return self._process.returncode

    def terminate(self):
        self.terminate_calls += 1
        self._process.terminate()

    def wait(self, timeout=None):
        return self._process.wait(timeout=timeout)

    def kill(self):
        self.kill_calls += 1
        self._process.kill()


def _spawn_fake_worker(monkeypatch, argv):
    created = []

    def popen(_command, **_kwargs):
        process = _FakeProcess(argv)
        created.append(process)
        return process

    monkeypatch.setattr(candidate_worker.subprocess, "Popen", popen)
    return created


def test_frozen_worker_uses_packaged_entrypoint(monkeypatch):
    monkeypatch.setattr(candidate_worker.sys, "frozen", True, raising=False)
    monkeypatch.setattr(candidate_worker.sys, "executable", "/dist/ecc")

    assert candidate_worker._worker_command() == ["/dist/ecc", "--ecc-candidate-worker"]


def test_cancel_terminates_worker_subprocess(tmp_path, monkeypatch):
    monkeypatch.setenv("ECC_CANDIDATE_STEP_ISOLATION", "1")
    created = _spawn_fake_worker(monkeypatch, [sys.executable, "-c", "import time; time.sleep(30)"])

    class Observer:
        runtime_operation = None

        def raise_if_cancelled(self):
            raise RuntimeOperationCancelled("candidate cancelled")

    with pytest.raises(RuntimeOperationCancelled, match="candidate cancelled"):
        candidate_worker.run_candidate_steps_isolated(
            _flow(tmp_path), [SimpleNamespace(name="place")], observer=Observer()
        )
    assert created[0].terminate_calls == 1
    assert created[0].kill_calls == 0
    assert created[0].poll() is not None


def test_worker_spawn_failure_fails_operation_without_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("ECC_CANDIDATE_STEP_ISOLATION", "1")

    def popen(*_args, **_kwargs):
        raise OSError("worker unavailable")

    monkeypatch.setattr(candidate_worker.subprocess, "Popen", popen)
    fallback_calls = []
    monkeypatch.setattr(
        "agent.workspace_api._run_candidate_step",
        lambda *args, **kwargs: fallback_calls.append(args),
    )
    with pytest.raises(RuntimeApiError, match="candidate worker process failed to start"):
        candidate_worker.run_candidate_steps_isolated(
            _flow(tmp_path), [SimpleNamespace(name="place")], observer=SimpleNamespace()
        )
    assert fallback_calls == []


def test_worker_result_is_collected_after_clean_exit(tmp_path, monkeypatch):
    monkeypatch.setenv("ECC_CANDIDATE_STEP_ISOLATION", "1")
    result_path = tmp_path / "analysis" / "candidate-worker.v1.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text(
        json.dumps({"schema_version": 1, "ok": True, "steps": [], "error": None}),
        encoding="utf-8",
    )
    created = _spawn_fake_worker(monkeypatch, [sys.executable, "-c", "pass"])

    candidate_worker.run_candidate_steps_isolated(
        _flow(tmp_path), [SimpleNamespace(name="place")], observer=SimpleNamespace()
    )

    payload = json.loads(created[0].stdin.data)
    assert payload["step_names"] == ["place"]
    assert payload["result_path"] == str(result_path)
    assert payload["parent_pid"] == os.getpid()
    assert created[0].terminate_calls == 0
