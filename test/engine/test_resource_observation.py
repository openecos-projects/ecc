import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from chipcompiler.engine import resource_observation as resources
from chipcompiler.engine.resource_observation import ResourceObservation, start_observation


def _process(root, pid, parent=0, *, start="100", pages=10, children=""):
    directory = root / str(pid)
    directory.mkdir(exist_ok=True)
    fields = ["S", str(parent)] + ["0"] * 17 + [start, "0", str(pages)]
    (directory / "stat").write_text(f"{pid} (example (worker)) " + " ".join(fields))
    task = directory / "task" / str(pid)
    task.mkdir(parents=True, exist_ok=True)
    (task / "children").write_text(children)


def _observer(root, monkeypatch, *, isolated=True):
    monkeypatch.setattr(resources, "_PROC", root)
    observation = ResourceObservation(100, isolated=isolated, step="place", tool="ecc")
    observation.start_id = "100"
    return observation


def test_rss_is_absolute_and_includes_children_of_all_threads(tmp_path, monkeypatch):
    _process(tmp_path, 100, pages=10, children="101")
    _process(tmp_path, 101, parent=100, pages=20)
    _process(tmp_path, 102, parent=100, pages=30)
    extra_thread = tmp_path / "100/task/999"
    extra_thread.mkdir()
    (extra_thread / "children").write_text("102 101")
    observation = _observer(tmp_path, monkeypatch)

    observation.sample()
    result = observation.finish()

    assert result["peak_rss_bytes"] == 60 * os.sysconf("SC_PAGE_SIZE")
    assert result["status"] == "available"
    assert result["sample_count"] == 1
    assert result["scope"] == "isolated_worker_process_tree"
    assert result["elapsed_seconds"] >= 0


def test_reused_root_pid_does_not_add_a_sample(tmp_path, monkeypatch):
    _process(tmp_path, 100, start="200")
    observation = _observer(tmp_path, monkeypatch)

    observation.sample()
    result = observation.finish()

    assert (result["status"], result["peak_rss_bytes"], result["sample_count"]) == (
        "unavailable",
        None,
        0,
    )
    assert result["reason"] == "Root PID identity changed"


def test_reparented_or_disappeared_children_are_partial(tmp_path, monkeypatch):
    _process(tmp_path, 100, children="101 102")
    _process(tmp_path, 101, parent=999)
    observation = _observer(tmp_path, monkeypatch)

    observation.sample()
    result = observation.finish()

    assert result["status"] == "partial"
    assert result["missed_processes"] == 2
    assert result["peak_rss_bytes"] == 10 * os.sysconf("SC_PAGE_SIZE")


def test_shared_process_scope_never_claims_step_attribution(tmp_path, monkeypatch):
    _process(tmp_path, 100)
    observation = _observer(tmp_path, monkeypatch, isolated=False)

    observation.sample()
    result = observation.finish()

    assert (result["scope"], result["status"]) == ("shared_process_tree", "partial")
    assert "Shared" in result["reason"]


def test_unavailable_proc_is_not_reported_as_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "_PROC", tmp_path)
    observation = start_observation(100, isolated=True, step="route", tool="ecc")

    result = observation.finish()

    assert (result["status"], result["peak_rss_bytes"], result["process_start_id"]) == (
        "unavailable",
        None,
        None,
    )


def test_sampling_errors_do_not_escape(monkeypatch):
    def denied(_pid):
        raise PermissionError("denied")

    monkeypatch.setattr(resources, "_stat", denied)
    observation = start_observation(100, isolated=True, step="sta", tool="ecc")

    assert observation.finish()["status"] == "unavailable"


@pytest.mark.skipif(not Path("/proc/self/stat").is_file(), reason="Linux proc required")
def test_real_worker_tree_is_sampled_and_sampler_stops(tmp_path):
    ready = tmp_path / "ready"
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import pathlib,subprocess,sys,time; "
            "child=subprocess.Popen([sys.executable,'-c',"
            "'import time; memory=bytearray(16000000); time.sleep(20)']); "
            "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(20)",
            str(ready),
        ],
        start_new_session=True,
    )
    observation = None
    try:
        deadline = time.monotonic() + 5
        while not ready.is_file() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.is_file()
        observation = start_observation(process.pid, isolated=True, step="route", tool="ecc")
        assert observation is not None
        time.sleep(0.3)
        result = observation.finish()
        assert result["status"] in {"available", "partial"}
        assert result["peak_rss_bytes"] > 16_000_000
        assert result["sample_count"] >= 1
        assert observation.thread is not None
        assert not observation.thread.is_alive()
    finally:
        if observation is not None:
            observation.finish()
        os.killpg(process.pid, 9)
        process.wait()


def test_in_process_execution_persists_shared_scope(monkeypatch, tmp_path):
    from chipcompiler.engine.step_execution import execute_tool_step

    monkeypatch.setenv("ECC_STEP_SUBPROCESS", "0")
    monkeypatch.setattr("chipcompiler.tools.run_step", lambda **_kwargs: True)
    workspace: Any = SimpleNamespace(logger=logging.getLogger("resource-test"))
    step: Any = SimpleNamespace(name="route", tool="ecc", log=SimpleNamespace(file=""))

    engine_db: Any = SimpleNamespace(engine=None)
    result = execute_tool_step(workspace, step, engine_db)

    assert result.error is None
    assert result.resource_observation is not None
    assert result.resource_observation["scope"] == "shared_process_tree"
    assert result.resource_observation["status"] in {"partial", "unavailable"}
    json.dumps(result.resource_observation, allow_nan=False)


def test_frozen_execution_is_explicitly_shared(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    observation = start_observation(os.getpid(), isolated=False, step="place", tool="ecc")

    result = observation.finish()

    assert result["frozen"] is True
    assert result["scope"] == "shared_process_tree"


def test_failed_execution_persists_facts_and_rerun_gets_a_new_identity(monkeypatch, tmp_path):
    from chipcompiler.data import EccStep, StateEnum, Workspace
    from chipcompiler.engine.flow import EngineFlow

    monkeypatch.setenv("ECC_STEP_SUBPROCESS", "0")
    monkeypatch.setattr("chipcompiler.tools.run_step", lambda **_kwargs: False)
    workspace = Workspace(directory=tmp_path)
    workspace.flow.path = tmp_path / "flow.json"
    workspace.flow.data = {"steps": [{"name": "route", "tool": "ecc", "state": "Unstart"}]}
    assert workspace.flow.path is not None
    workspace.flow.path.write_text(json.dumps(workspace.flow.data))
    (tmp_path / "home").mkdir()
    flow = EngineFlow(workspace)
    step = EccStep(name="route", directory=tmp_path, tool="ecc")
    flow.workspace_steps = [step]
    vars(flow)["engine_db"] = SimpleNamespace(engine=None)

    flow.run_step(step)
    first = json.loads(workspace.flow.path.read_text())["steps"][0]
    flow.run_step(step, rerun=True)
    second = json.loads(workspace.flow.path.read_text())["steps"][0]

    assert (
        first["resource_observation"]["attempt_id"] != second["resource_observation"]["attempt_id"]
    )
    assert second["state"] == StateEnum.Imcomplete.value
    assert second["resource_observation"]["scope"] == "shared_process_tree"
    flow.clear_states()
    assert "resource_observation" not in json.loads(workspace.flow.path.read_text())["steps"][0]


def test_skipping_a_successful_step_does_not_create_a_new_measurement(monkeypatch, tmp_path):
    from chipcompiler.data import EccStep, Workspace
    from chipcompiler.engine.flow import EngineFlow

    workspace = Workspace(directory=tmp_path)
    workspace.flow.data = {
        "steps": [
            {
                "name": "route",
                "tool": "ecc",
                "state": "Success",
                "resource_observation": {"attempt_id": "previous-execution"},
            }
        ]
    }
    workspace.flow.path = tmp_path / "flow.json"
    assert workspace.flow.path is not None
    workspace.flow.path.write_text(json.dumps(workspace.flow.data))
    (tmp_path / "home").mkdir()
    flow = EngineFlow(workspace)
    step = EccStep(name="route", directory=tmp_path, tool="ecc")
    flow.workspace_steps = [step]
    monkeypatch.setattr(
        "chipcompiler.engine.flow.execute_tool_step",
        lambda *_args, **_kwargs: pytest.fail("Skipped step ran"),
    )

    flow.run_step(step)

    assert workspace.flow.data.get("steps", [])[0].get("resource_observation") == {
        "attempt_id": "previous-execution"
    }


def test_start_commit_failure_preserves_previous_resource_facts(monkeypatch, tmp_path):
    from chipcompiler.data import EccStep, Workspace
    from chipcompiler.engine.flow import EngineFlow

    workspace = Workspace(directory=tmp_path)
    workspace.flow.data = {
        "steps": [
            {
                "name": "route",
                "tool": "ecc",
                "state": "Unstart",
                "info": {},
                "resource_observation": {"attempt_id": "previous-execution"},
            }
        ]
    }
    workspace.flow.path = tmp_path / "flow.json"
    assert workspace.flow.path is not None
    workspace.flow.path.write_text(json.dumps(workspace.flow.data))
    (tmp_path / "home").mkdir()
    flow = EngineFlow(workspace)
    step = EccStep(name="route", directory=tmp_path, tool="ecc")
    flow.workspace_steps = [step]
    before = json.loads(json.dumps(workspace.flow.data))
    monkeypatch.setattr(flow, "save", lambda: False)
    observer = SimpleNamespace(runtime_operation={"operation_id": "new-operation"})

    with pytest.raises(RuntimeError, match="failed to persist runtime operation marker"):
        flow.run_step(step, rerun=True, observer=observer)

    assert workspace.flow.data == before
