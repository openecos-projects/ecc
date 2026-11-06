import io
import json
import logging
import os
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from chipcompiler.data import OutputPaths
from chipcompiler.data.workspace import Flow
from chipcompiler.engine import step_subprocess


def _ns(**kwargs: object) -> Any:
    return SimpleNamespace(**kwargs)


@pytest.fixture(autouse=True)
def _disable_process_guards(monkeypatch):
    monkeypatch.setattr(step_subprocess.worker, "arm_parent_death_signal", lambda _pid: None)
    monkeypatch.setattr(step_subprocess.worker, "_start_parent_death_watchdog", lambda: None)


def _workspace_step(tmp_path, name="place", tool="ecc"):
    log_file = tmp_path / "log" / "step.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    return _ns(
        name=name,
        tool=tool,
        directory=tmp_path / f"{name}_{tool}",
        output=OutputPaths(),
        log=_ns(file=str(log_file)),
    )


def _workspace(tmp_path):
    from chipcompiler.data.parameter import Parameters, save_parameter

    parameters = Parameters(
        path=tmp_path / "home/params.toml",
        data={"design": "example", "top_module": "example", "pdk": "ics55", "clock": "clk"},
    )
    assert save_parameter(parameters)
    return _ns(
        directory=str(tmp_path),
        logger=logging.getLogger("ecc-test"),
        parameters=parameters,
        flow=Flow(path=tmp_path / "home/flow.json", data={"schema_version": 2, "steps": []}),
    )


class _FakeFlow:
    engine_db = _ns(initialization_error=None, engine=None)
    check_result = True
    placement_only = False
    _step: Any = None

    def __init__(self, workspace):
        self.workspace = workspace
        self.initialized_for = None

    def init_db_engine_for_step(self, step):
        self.initialized_for = step
        return True

    def check_step_result(self, workspace_step):
        return self.check_result

    def _is_placement_only_step(self, workspace_step):
        return self.placement_only


def _patch_worker_dependencies(monkeypatch, tmp_path, step, flow, run_step, *, built=None):
    def load_workspace(directory, *, read_only=False):
        assert read_only is True
        return _workspace(tmp_path)

    def create_step(**kwargs):
        assert kwargs["initialize_config"] is False
        return step if built is None else built

    monkeypatch.setattr("chipcompiler.data.load_workspace", load_workspace)
    monkeypatch.setattr("chipcompiler.engine.flow.EngineFlow", lambda workspace: flow)
    monkeypatch.setattr("chipcompiler.tools.create_step", create_step)
    monkeypatch.setattr("chipcompiler.tools.run_step", run_step)
    monkeypatch.setattr("chipcompiler.tools.save_layout_image", lambda **_kwargs: True)


def _payload_stream(tmp_path, step, result_path, *, layout_image=True, attempt_id="test-attempt"):
    from chipcompiler.data.handshake import StepInputs, StepRequest, write_request

    request = StepRequest(
        workspace_directory=tmp_path,
        step=step.name,
        tool=step.tool,
        step_directory=f"{step.name}_{step.tool}",
        attempt_id="test-attempt",
        inputs=StepInputs(),
        design_source=None,
        upstream={},
        final_step=False,
        layout_image=layout_image,
    )
    write_request(request)
    payload = {
        "schema_version": 2,
        "step_directory": str(request.directory),
        "attempt_id": attempt_id,
        "result_path": str(result_path),
        "parent_pid": os.getpid(),
    }
    return io.StringIO(json.dumps(payload))


def _run_main(
    monkeypatch,
    tmp_path,
    step,
    flow,
    run_step,
    *,
    layout_image=True,
    save_layout_image=None,
):
    _patch_worker_dependencies(monkeypatch, tmp_path, step, flow, run_step)
    if save_layout_image is not None:
        monkeypatch.setattr("chipcompiler.tools.save_layout_image", save_layout_image)
    monkeypatch.setattr(
        sys,
        "stdin",
        _payload_stream(
            tmp_path, step, tmp_path / "out" / "result.json", layout_image=layout_image
        ),
    )
    exit_code = step_subprocess.main()
    result_path = tmp_path / "out" / "result.json"
    return exit_code, json.loads(result_path.read_text(encoding="utf-8"))


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
    assert result["attempt_id"] == "test-attempt"
    assert result["error"] is None
    assert result["events"] == [
        {"type": "subflow_stage", "subflow_step": {"name": "load", "state": "Ongoing"}}
    ]
    assert events == ["ran"]
    assert flow.initialized_for is step


def test_worker_main_rejects_ledger_save_without_writing(monkeypatch, tmp_path):
    from contextlib import nullcontext

    from chipcompiler.data.workspace.flow_ledger import save_ledger

    step = _workspace_step(tmp_path)
    result_path = tmp_path / "out" / "result.json"
    workspace = _workspace(tmp_path)
    flow = _FakeFlow(workspace)
    flow._step = step
    ledger_path = workspace.flow.path
    assert ledger_path is not None
    ledger_path.write_text(json.dumps(workspace.flow.data), encoding="utf-8")
    before = ledger_path.read_bytes()

    monkeypatch.setattr(
        "chipcompiler.data.load_workspace",
        lambda directory, *, read_only=False: workspace,
    )
    monkeypatch.setattr("chipcompiler.engine.flow.EngineFlow", lambda _workspace: flow)
    monkeypatch.setattr("chipcompiler.tools.create_step", lambda **_kwargs: step)
    monkeypatch.setattr(
        "chipcompiler.utility.log.capture_stdio_to_file", lambda _path: nullcontext()
    )

    def save_from_tool(workspace, step, ecc_module=None):
        save_ledger(workspace.flow)
        return True

    monkeypatch.setattr("chipcompiler.tools.run_step", save_from_tool)
    monkeypatch.setattr(sys, "stdin", _payload_stream(tmp_path, step, result_path))

    assert step_subprocess.main() == 1
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["done"] is True
    assert result["ok"] is False
    assert "read-only" in result["error"]
    assert workspace.flow.read_only is True
    assert ledger_path.read_bytes() == before


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


@pytest.mark.parametrize(
    ("built", "message"),
    [
        (None, "could not be built"),
        (_ns(name="place", tool="ecc", directory="/elsewhere/place_ecc"), "builds into"),
    ],
)
def test_worker_main_records_a_step_it_cannot_build(monkeypatch, tmp_path, built, message):
    step = _workspace_step(tmp_path)
    result_path = tmp_path / "out" / "result.json"
    flow = _FakeFlow(_workspace(tmp_path))

    _patch_worker_dependencies(monkeypatch, tmp_path, step, flow, lambda *a, **k: True)
    monkeypatch.setattr("chipcompiler.tools.create_step", lambda **_kwargs: built)
    monkeypatch.setattr(sys, "stdin", _payload_stream(tmp_path, step, result_path))

    assert step_subprocess.main() == 1
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["done"] is True
    assert message in result["error"]


def test_worker_main_rejects_a_request_from_another_attempt(monkeypatch, tmp_path):
    step = _workspace_step(tmp_path)
    result_path = tmp_path / "out" / "result.json"
    _patch_worker_dependencies(
        monkeypatch, tmp_path, step, _FakeFlow(_workspace(tmp_path)), lambda *a, **k: True
    )
    monkeypatch.setattr(
        sys, "stdin", _payload_stream(tmp_path, step, result_path, attempt_id="stale")
    )

    assert step_subprocess.main() == 1
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert "belongs to another attempt" in result["error"]


def test_worker_main_records_exceptions(monkeypatch, tmp_path):
    step = _workspace_step(tmp_path)
    result_path = tmp_path / "out" / "result.json"

    def broken_loader(directory, *, read_only=False):
        raise OSError("no workspace")

    monkeypatch.setattr("chipcompiler.data.load_workspace", broken_loader)
    monkeypatch.setattr(sys, "stdin", _payload_stream(tmp_path, step, result_path))

    assert step_subprocess.main() == 1
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["done"] is True
    assert result["ok"] is False
    assert "OSError" in result["error"]


@pytest.mark.parametrize(
    ("tool_ok", "outputs_complete", "placement_only", "payload_image", "expected_calls"),
    [
        (False, True, False, True, ["tool"]),
        (True, False, False, True, ["tool", "check"]),
        (True, True, True, True, ["tool", "check"]),
        (True, True, False, False, ["tool", "check"]),
        (True, True, False, True, ["tool", "check", "image"]),
    ],
)
def test_worker_layout_image_gate(
    monkeypatch,
    tmp_path,
    tool_ok,
    outputs_complete,
    placement_only,
    payload_image,
    expected_calls,
):
    step = _workspace_step(tmp_path)
    flow = _FakeFlow(_workspace(tmp_path))
    flow._step = step
    calls = []

    def run_step(*_args, **_kwargs):
        calls.append("tool")
        return tool_ok

    monkeypatch.setattr(
        flow,
        "check_step_result",
        lambda **_kwargs: calls.append("check") or outputs_complete,
    )
    monkeypatch.setattr(flow, "_is_placement_only_step", lambda _step: placement_only)

    def render(**_kwargs):
        calls.append("image")
        return True

    exit_code, _result = _run_main(
        monkeypatch,
        tmp_path,
        step,
        flow,
        run_step,
        layout_image=payload_image,
        save_layout_image=render,
    )

    assert calls == expected_calls
    assert (exit_code == 0) is tool_ok


def test_worker_layout_image_false_is_logged_without_failing(monkeypatch, tmp_path, caplog):
    step = _workspace_step(tmp_path)
    flow = _FakeFlow(_workspace(tmp_path))
    flow._step = step
    with caplog.at_level(logging.WARNING, logger="ecc-test"):
        exit_code, result = _run_main(
            monkeypatch,
            tmp_path,
            step,
            flow,
            lambda *_args, **_kwargs: True,
            save_layout_image=lambda **_kwargs: False,
        )

    assert exit_code == 0
    assert result["ok"] is True
    assert "layout image was not generated" in caplog.text


def test_worker_layout_image_exception_fails_the_step(monkeypatch, tmp_path):
    step = _workspace_step(tmp_path)
    flow = _FakeFlow(_workspace(tmp_path))
    flow._step = step

    def explode(**_kwargs):
        raise RuntimeError("render failed")

    exit_code, result = _run_main(
        monkeypatch,
        tmp_path,
        step,
        flow,
        lambda *_args, **_kwargs: True,
        save_layout_image=explode,
    )

    assert exit_code == 1
    assert result["done"] is True
    assert result["ok"] is False
    assert "render failed" in result["error"]


@pytest.mark.parametrize(("tool_ok", "status"), [(True, "success"), (False, "failed")])
def test_worker_publishes_its_response(monkeypatch, tmp_path, tool_ok, status):
    from chipcompiler.data.handshake import load_response

    step = _workspace_step(tmp_path)
    flow = _FakeFlow(_workspace(tmp_path))

    _run_main(monkeypatch, tmp_path, step, flow, lambda *_args, **_kwargs: tool_ok)

    response = load_response(step.directory)
    assert response is not None
    assert (response.attempt_id, response.status) == ("test-attempt", status)


def test_worker_refuses_a_step_whose_required_design_data_is_missing(monkeypatch, tmp_path):
    step = _workspace_step(tmp_path, name="emir")
    ran = []

    exit_code, result = _run_main(
        monkeypatch,
        tmp_path,
        step,
        _FakeFlow(_workspace(tmp_path)),
        lambda *_args, **_kwargs: ran.append("tool") or True,
    )

    assert (exit_code, ran) == (1, [])
    assert "emir cannot run: missing power" in result["error"]


def test_worker_publishes_a_failed_response_when_its_tool_raises(monkeypatch, tmp_path):
    from chipcompiler.data.handshake import ResponseStatus, load_response

    step = _workspace_step(tmp_path)

    def explode(*_args, **_kwargs):
        raise RuntimeError("SDC contains invalid constraints")

    exit_code, result = _run_main(
        monkeypatch, tmp_path, step, _FakeFlow(_workspace(tmp_path)), explode
    )

    response = load_response(step.directory)
    assert (exit_code, "SDC contains invalid constraints" in result["error"]) == (1, True)
    assert response is not None
    assert (response.attempt_id, response.status) == ("test-attempt", ResponseStatus.FAILED)
