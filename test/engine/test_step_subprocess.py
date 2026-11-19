import json
import sys
from pathlib import Path

import pytest

from chipcompiler.engine.step import process as step_subprocess
from chipcompiler.engine.step.execution import execute_tool_step
from test.engine import step_worker_fakes as fakes

pytestmark = pytest.mark.real_step_worker


@pytest.fixture(autouse=True)
def _stub_worker_process(monkeypatch):
    fakes.stub_worker_process(monkeypatch)


def test_cli_dispatches_step_worker(monkeypatch):
    from chipcompiler.cli import app as app_module

    monkeypatch.setattr(step_subprocess, "main", lambda: 17)

    assert app_module.invoke_typer_app(["--ecc-worker", "chipcompiler.engine.step.process"]) == 17


def test_rcx_worker_restores_outputs_and_preserves_shared_sta_list(monkeypatch, tmp_path):
    from chipcompiler.data import EccOutput

    step = fakes.workspace_step(tmp_path, name="rcx")
    step.output = EccOutput(dir=tmp_path / "output")
    shared_sta_inputs = step.output.spef
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    monkeypatch.setattr(
        step_subprocess.worker.subprocess,
        "Popen",
        fakes.spawn_with_result(
            result_path,
            {
                "done": True,
                "ok": True,
                "events": [],
            },
            parasitics=(tmp_path / "output/sample_TYPICAL_25C.spef",),
        ),
    )

    result = step_subprocess.execute_step_subprocess(fakes.workspace(tmp_path), step)

    assert result.error is None
    assert shared_sta_inputs == [tmp_path / "output/sample_TYPICAL_25C.spef"]
    assert step.output.spef is shared_sta_inputs


def test_rcx_outputs_are_restored_when_worker_image_fails(monkeypatch, tmp_path):
    from chipcompiler.data import EccOutput

    step = fakes.workspace_step(tmp_path, name="rcx")
    step.output = EccOutput(dir=tmp_path / "output")
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    monkeypatch.setattr(
        step_subprocess.worker.subprocess,
        "Popen",
        fakes.spawn_with_result(
            result_path,
            {
                "done": True,
                "ok": False,
                "error": "render failed",
                "events": [],
            },
            returncode=1,
            parasitics=(tmp_path / "output/sample_TYPICAL_25C.spef",),
        ),
    )

    result = step_subprocess.execute_step_subprocess(fakes.workspace(tmp_path), step)

    assert result.error is not None
    assert "render failed" in result.error
    assert step.output.spef == [tmp_path / "output/sample_TYPICAL_25C.spef"]


def test_rcx_success_result_with_nonzero_exit_does_not_restore(monkeypatch, tmp_path):
    from chipcompiler.data import EccOutput

    step = fakes.workspace_step(tmp_path, name="rcx")
    step.output = EccOutput(dir=tmp_path / "output")
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    monkeypatch.setattr(
        step_subprocess.worker.subprocess,
        "Popen",
        fakes.spawn_with_result(
            result_path,
            {
                "done": True,
                "ok": True,
                "events": [],
            },
            returncode=-11,
            parasitics=(tmp_path / "output/sample_TYPICAL_25C.spef",),
        ),
    )

    result = step_subprocess.execute_step_subprocess(fakes.workspace(tmp_path), step)

    assert result.error is not None
    assert "code -11" in result.error
    assert step.output.spef == []


@pytest.mark.parametrize(
    "names", [[], ["../escape.spef"], ["/tmp/escape.spef"], ["dup.spef", "dup.spef"], ["x.txt"]]
)
def test_rcx_worker_rejects_invalid_output_references(tmp_path, names):
    from chipcompiler.data import EccOutput

    step = fakes.workspace_step(tmp_path, name="rcx")
    step.output = EccOutput(dir=tmp_path / "output")
    spef = tuple(tmp_path / "output" / name for name in names)
    assert step_subprocess._restore_rcx_outputs(step, spef)
    assert step.output.spef == []


def test_step_worker_runs_in_workspace_directory(monkeypatch, tmp_path):
    workspace = fakes.workspace(tmp_path)
    step = fakes.workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    spawn_with_result = fakes.spawn_with_result(
        result_path, {"done": True, "ok": True, "events": []}
    )
    options = {}

    def spawn(*args, **kwargs):
        options.update(kwargs)
        return spawn_with_result(*args, **kwargs)

    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", spawn)
    result = step_subprocess.execute_step_subprocess(workspace, step)

    assert result.error is None
    assert options["cwd"] == str(workspace.directory)


def test_sta_step_memory_includes_corner_workers(monkeypatch, tmp_path):
    from chipcompiler.data import EccOutput
    from chipcompiler.tools.ecc import sta_parallel

    step = fakes.workspace_step(tmp_path, name="sta")
    step.output = EccOutput()
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    monkeypatch.setattr(
        step_subprocess.worker.subprocess,
        "Popen",
        fakes.spawn_with_result(result_path, {"done": True, "ok": True, "events": []}),
    )
    readings = iter([30, 60])
    monkeypatch.setattr(sta_parallel, "get_sta_process_rss_mb", lambda _pid: next(readings))
    result = step_subprocess.execute_step_subprocess(fakes.workspace(tmp_path), step)
    assert result.error is None
    assert result.peak_memory_mb == 30


@pytest.mark.parametrize("worker_ok", [True, False])
def test_worker_parameter_updates_are_visible_before_terminal_snapshot(
    monkeypatch, tmp_path, worker_ok
):
    from chipcompiler.data.parameter import load_parameter, save_parameter

    workspace = fakes.workspace(tmp_path)
    step = fakes.workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME

    def spawn(*_args, **_kwargs):
        parameters = load_parameter(workspace.parameters.path)
        parameters.data["core"] = {"aspect_ratio": 0.8, "size": [8.0, 10.0]}
        assert save_parameter(parameters)
        result_path.write_text(
            json.dumps(
                {
                    "attempt_id": "test-attempt",
                    "done": True,
                    "ok": worker_ok,
                    "error": "boom",
                }
            )
        )
        fakes.publish_response(result_path)
        return fakes.FakePopen(poll_script=[0])

    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", spawn)
    result = step_subprocess.execute_step_subprocess(workspace, step)

    assert (result.error is None) is worker_ok
    assert workspace.parameters.data == load_parameter(workspace.parameters.path).data
    assert workspace.parameters.data["core"] == {"aspect_ratio": 0.8, "size": [8.0, 10.0]}


def test_worker_corrupt_parameters_prevent_success(monkeypatch, tmp_path):
    workspace = fakes.workspace(tmp_path)
    step = fakes.workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME

    def spawn(*_args, **_kwargs):
        workspace.parameters.path.write_text("{broken")
        result_path.write_text(json.dumps({"attempt_id": "test-attempt", "done": True, "ok": True}))
        fakes.publish_response(result_path)
        return fakes.FakePopen(poll_script=[0])

    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", spawn)
    result = step_subprocess.execute_step_subprocess(workspace, step)
    assert result.error is not None
    assert "parameters could not be reloaded" in result.error


def test_frozen_execution_uses_packaged_worker_dispatch(monkeypatch, tmp_path):
    step = fakes.workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    commands = []
    spawn_result = fakes.spawn_with_result(result_path, {"done": True, "ok": True, "events": []})

    def spawn(arguments, **kwargs):
        commands.append(arguments)
        return spawn_result(arguments, **kwargs)

    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", spawn)

    result = execute_tool_step(fakes.workspace(tmp_path), step, None)

    assert result.error is None
    assert commands == [[sys.executable, "--ecc-worker", "chipcompiler.engine.step.process"]]


def test_execute_tool_step_selects_worker_module(monkeypatch, tmp_path):
    step = fakes.workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    commands = []
    spawn_result = fakes.spawn_with_result(result_path, {"done": True, "ok": True, "events": []})

    def spawn(arguments, **kwargs):
        commands.append(arguments)
        return spawn_result(arguments, **kwargs)

    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", spawn)

    result = execute_tool_step(
        fakes.workspace(tmp_path), step, None, worker_module="agent.step_worker"
    )

    assert result.error is None
    assert commands == [[sys.executable, "-m", "agent.step_worker"]]
