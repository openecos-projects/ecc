import os
import shutil
import threading

import pytest

from agent.runtime_env import prepare_agent_runtime_environment
from chipcompiler.runtime.operations import RuntimeOperationFailed, RuntimeOperationManager


@pytest.mark.parametrize(
    "relative_executable",
    ("bin/Sizer", "build/src/Sizer", "build/Sizer", "Sizer"),
)
def test_agent_runtime_prepares_packaged_sizer_environment(
    tmp_path,
    monkeypatch,
    relative_executable,
):
    runtime_root = tmp_path / "ecc-sizer"
    executable = runtime_root / relative_executable
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("CHIPCOMPILER_ECC_SIZER_ROOT", str(runtime_root))
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    monkeypatch.setenv("LD_LIBRARY_PATH", "/packaged/lib")
    monkeypatch.setenv("LD_PRELOAD", "/packaged/preload.so")

    prepare_agent_runtime_environment()

    assert shutil.which("Sizer") == str(executable.resolve())
    assert os.environ["LD_LIBRARY_PATH"] == "/packaged/lib"
    assert os.environ["LD_PRELOAD"] == "/packaged/preload.so"


def test_agent_runtime_without_packaged_sizer_preserves_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("CHIPCOMPILER_ECC_SIZER_ROOT", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("LD_LIBRARY_PATH", "/host/lib")
    monkeypatch.setenv("LD_PRELOAD", "/host/preload.so")

    prepare_agent_runtime_environment()

    assert os.environ["PATH"] == str(tmp_path)
    assert os.environ["LD_LIBRARY_PATH"] == "/host/lib"
    assert os.environ["LD_PRELOAD"] == "/host/preload.so"


def test_structured_candidate_failure_preserves_partial_result() -> None:
    events = []
    manager = RuntimeOperationManager(events.append)
    partial = {"candidateRootRef": ".agent/candidates/candidate-1"}

    def runner(_observer):
        raise RuntimeOperationFailed("candidate Harden failed", result=partial)

    started = manager.start(
        workspace_id="workspace-1",
        kind="candidate_rerun",
        origin="agent",
        rerun=True,
        step="place",
        idempotency_key="failed-candidate",
        runner=runner,
    )

    status = _wait_for_terminal(manager, started["operationId"])
    assert status["state"] == "failed"
    assert status["result"] == partial
    assert _wait_for_event(events, "operation.failed")["payload"]["result"] == partial


def test_cancelled_candidate_operation_preserves_runner_result() -> None:
    entered = threading.Event()
    release = threading.Event()
    manager = RuntimeOperationManager()

    def runner(_observer):
        entered.set()
        assert release.wait(timeout=1)
        return {"candidateRootRef": ".agent/candidates/candidate-1"}

    started = manager.start(
        workspace_id="workspace-1",
        kind="candidate_rerun",
        origin="agent",
        rerun=True,
        step="place",
        idempotency_key="cancelled-candidate",
        runner=runner,
    )
    assert entered.wait(timeout=1)
    assert manager.request_cancel(started["operationId"])["accepted"] is True
    release.set()

    status = _wait_for_terminal(manager, started["operationId"])
    assert status["state"] == "cancelled"
    assert status["result"] == {"candidateRootRef": ".agent/candidates/candidate-1"}


def _wait_for_event(events: list[dict], event_type: str) -> dict:
    for _ in range(200):
        for event in events:
            if event["type"] == event_type:
                return event
        threading.Event().wait(0.01)
    raise AssertionError(f"event not received: {event_type}")


def _wait_for_terminal(manager: RuntimeOperationManager, operation_id: str) -> dict:
    for _ in range(100):
        status = manager.operation_status(operation_id)
        if status["state"] in {"succeeded", "failed", "cancelled"}:
            return status
        threading.Event().wait(0.01)
    return manager.operation_status(operation_id)
