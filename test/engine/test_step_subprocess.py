import io
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from chipcompiler.engine import step_subprocess
from chipcompiler.engine.step_execution import execute_tool_step

pytestmark = pytest.mark.real_step_worker


def _terminate_fake(process):
    if process.poll() is None:
        process.terminate()
    process.wait()


def _ns(**kwargs: object) -> Any:
    return SimpleNamespace(**kwargs)


@pytest.fixture(autouse=True)
def _no_parent_death_signal(monkeypatch):
    # main() runs in the pytest process here; arming PR_SET_PDEATHSIG would
    # SIGKILL the runner when the recorded parent pid is not our ppid.
    monkeypatch.setattr(step_subprocess.worker, "arm_parent_death_signal", lambda parent_pid: None)
    monkeypatch.setattr(step_subprocess.worker, "_start_parent_death_watchdog", lambda: None)
    monkeypatch.setattr(step_subprocess.worker, "terminate_process_group", _terminate_fake)
    monkeypatch.setattr(step_subprocess, "new_attempt_id", lambda: "test-attempt")


def _workspace_step(tmp_path, name="place", tool="ecc"):
    from chipcompiler.data import StepInput

    log_file = tmp_path / "log" / "step.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    return _ns(
        name=name,
        tool=tool,
        directory=str(tmp_path / f"{name}_{tool}"),
        input=StepInput(),
        log=_ns(file=str(log_file)),
    )


def _workspace(tmp_path):
    from chipcompiler.data.parameter import Parameters, save_parameter
    from chipcompiler.data.workspace import Flow

    parameters = Parameters(
        path=tmp_path / "home/params.toml",
        data={"design": "example", "top_module": "example", "pdk": "ics55", "clock": "clk"},
    )
    assert save_parameter(parameters)
    return _ns(
        directory=tmp_path,
        logger=logging.getLogger("ecc-test"),
        parameters=parameters,
        flow=Flow(path=tmp_path / "home/flow.json", data={"schema_version": 2, "steps": []}),
    )


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


def _publish_response(result_path, *, parasitics=()):
    """Write the rsp.json the worker publishes for the request the parent wrote."""
    from chipcompiler.data.handshake import (
        DesignFiles,
        ResponseStatus,
        StepResponse,
        load_request,
        write_response,
    )
    from chipcompiler.data.types import AnalysisData

    (request_path,) = result_path.parent.parent.glob("*/req.json")
    request = load_request(request_path.parent)
    write_response(
        request.directory,
        StepResponse(
            step=request.step,
            tool=request.tool,
            attempt_id=request.attempt_id,
            status=ResponseStatus.SUCCESS,
            design=DesignFiles(),
            design_states=frozenset(),
            outputs={AnalysisData.PARASITICS: tuple(parasitics)} if parasitics else {},
            design_source=request.design_source,
            upstream=request.upstream,
            warnings=frozenset(),
        ),
    )


def _spawn_with_result(result_path, result, *, returncode=0, parasitics=()):
    def spawn(*_args, **_kwargs):
        result_path.write_text(json.dumps({"attempt_id": "test-attempt", **result}))
        if result.get("done"):
            _publish_response(result_path, parasitics=parasitics)
        return _FakePopen(poll_script=[returncode])

    return spawn


def test_rcx_worker_restores_outputs_and_preserves_shared_sta_list(monkeypatch, tmp_path):
    from chipcompiler.data import EccOutput

    step = _workspace_step(tmp_path, name="RCX")
    step.output = EccOutput(dir=tmp_path / "output")
    shared_sta_inputs = step.output.spef
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    monkeypatch.setattr(
        step_subprocess.worker.subprocess,
        "Popen",
        _spawn_with_result(
            result_path,
            {
                "done": True,
                "ok": True,
                "events": [],
            },
            parasitics=(tmp_path / "output/sample_TYPICAL_25C.spef",),
        ),
    )

    result = step_subprocess.execute_step_subprocess(_workspace(tmp_path), step)

    assert result.error is None
    assert shared_sta_inputs == [tmp_path / "output/sample_TYPICAL_25C.spef"]
    assert step.output.spef is shared_sta_inputs


def test_rcx_outputs_are_restored_when_worker_image_fails(monkeypatch, tmp_path):
    from chipcompiler.data import EccOutput

    step = _workspace_step(tmp_path, name="RCX")
    step.output = EccOutput(dir=tmp_path / "output")
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    monkeypatch.setattr(
        step_subprocess.worker.subprocess,
        "Popen",
        _spawn_with_result(
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

    result = step_subprocess.execute_step_subprocess(_workspace(tmp_path), step)

    assert result.error is not None
    assert "render failed" in result.error
    assert step.output.spef == [tmp_path / "output/sample_TYPICAL_25C.spef"]


def test_rcx_success_result_with_nonzero_exit_does_not_restore(monkeypatch, tmp_path):
    from chipcompiler.data import EccOutput

    step = _workspace_step(tmp_path, name="RCX")
    step.output = EccOutput(dir=tmp_path / "output")
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    monkeypatch.setattr(
        step_subprocess.worker.subprocess,
        "Popen",
        _spawn_with_result(
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

    result = step_subprocess.execute_step_subprocess(_workspace(tmp_path), step)

    assert result.error is not None
    assert "code -11" in result.error
    assert step.output.spef == []


@pytest.mark.parametrize(
    "names", [[], ["../escape.spef"], ["/tmp/escape.spef"], ["dup.spef", "dup.spef"], ["x.txt"]]
)
def test_rcx_worker_rejects_invalid_output_references(tmp_path, names):
    from chipcompiler.data import EccOutput

    step = _workspace_step(tmp_path, name="RCX")
    step.output = EccOutput(dir=tmp_path / "output")
    spef = tuple(tmp_path / "output" / name for name in names)
    assert step_subprocess._restore_rcx_outputs(step, spef)
    assert step.output.spef == []


def test_sta_step_memory_includes_corner_workers(monkeypatch, tmp_path):
    from chipcompiler.data import EccOutput
    from chipcompiler.tools.ecc import sta_parallel

    step = _workspace_step(tmp_path, name="sta")
    step.output = EccOutput()
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    monkeypatch.setattr(
        step_subprocess.worker.subprocess,
        "Popen",
        _spawn_with_result(result_path, {"done": True, "ok": True, "events": []}),
    )
    readings = iter([30, 60])
    monkeypatch.setattr(sta_parallel, "get_sta_process_rss_mb", lambda _pid: next(readings))
    result = step_subprocess.execute_step_subprocess(_workspace(tmp_path), step)
    assert result.error is None
    assert result.peak_memory_mb == 30


@pytest.mark.parametrize("worker_ok", [True, False])
def test_worker_parameter_updates_are_visible_before_terminal_snapshot(
    monkeypatch, tmp_path, worker_ok
):
    from chipcompiler.data.parameter import load_parameter, save_parameter

    workspace = _workspace(tmp_path)
    step = _workspace_step(tmp_path)
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
        _publish_response(result_path)
        return _FakePopen(poll_script=[0])

    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", spawn)
    result = step_subprocess.execute_step_subprocess(workspace, step)

    assert (result.error is None) is worker_ok
    assert workspace.parameters.data == load_parameter(workspace.parameters.path).data
    assert workspace.parameters.data["core"] == {"aspect_ratio": 0.8, "size": [8.0, 10.0]}


def test_worker_corrupt_parameters_prevent_success(monkeypatch, tmp_path):
    workspace = _workspace(tmp_path)
    step = _workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME

    def spawn(*_args, **_kwargs):
        workspace.parameters.path.write_text("{broken")
        result_path.write_text(json.dumps({"attempt_id": "test-attempt", "done": True, "ok": True}))
        _publish_response(result_path)
        return _FakePopen(poll_script=[0])

    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", spawn)
    result = step_subprocess.execute_step_subprocess(workspace, step)
    assert result.error is not None
    assert "parameters could not be reloaded" in result.error


def test_frozen_execution_uses_packaged_worker_dispatch(monkeypatch, tmp_path):
    step = _workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    commands = []
    spawn_result = _spawn_with_result(result_path, {"done": True, "ok": True, "events": []})

    def spawn(arguments, **kwargs):
        commands.append(arguments)
        return spawn_result(arguments, **kwargs)

    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", spawn)

    result = execute_tool_step(_workspace(tmp_path), step, None)

    assert result.error is None
    assert commands == [[sys.executable, "--ecc-worker", "chipcompiler.engine.step_subprocess"]]


def test_execute_tool_step_selects_worker_module(monkeypatch, tmp_path):
    step = _workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    commands = []
    spawn_result = _spawn_with_result(result_path, {"done": True, "ok": True, "events": []})

    def spawn(arguments, **kwargs):
        commands.append(arguments)
        return spawn_result(arguments, **kwargs)

    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", spawn)

    result = execute_tool_step(_workspace(tmp_path), step, None, worker_module="agent.step_worker")

    assert result.error is None
    assert commands == [[sys.executable, "-m", "agent.step_worker"]]


def test_execute_step_subprocess_reports_worker_crash(monkeypatch, tmp_path):
    fake = _FakePopen(returncode=-11)
    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", lambda *a, **k: fake)
    step = _workspace_step(tmp_path)
    result = execute_tool_step(_workspace(tmp_path), step, None)

    from chipcompiler.data.handshake import load_request

    payload = json.loads(fake.stdin.getvalue())
    request = load_request(Path(step.directory))
    assert {key: payload[key] for key in ("step_directory", "attempt_id")} == {
        "step_directory": str(request.directory),
        "attempt_id": "test-attempt",
    }
    assert (request.step, request.tool, request.layout_image) == ("place", "ecc", True)
    assert payload["result_path"].endswith(step_subprocess._RESULT_NAME)
    assert result.error is not None
    assert "code -11" in result.error


def test_failed_worker_reloads_subflow_for_interrupted_finalization(monkeypatch, tmp_path):
    from chipcompiler.data import StateEnum, SubflowState
    from chipcompiler.engine.flow_completion import finalize_interrupted_subflow

    step = _workspace_step(tmp_path)
    subflow_path = tmp_path / "subflow.json"
    step.subflow = SubflowState(path=subflow_path, steps=[])
    subflow_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "path": str(subflow_path),
                "steps": [{"name": "load", "state": StateEnum.Ongoing.value}],
            }
        ),
        encoding="utf-8",
    )
    fake = _FakePopen(poll_script=[-11])
    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", lambda *_args, **_kwargs: fake)

    result = execute_tool_step(_workspace(tmp_path), step, None)

    assert result.error is not None
    assert "code -11" in result.error
    assert step.subflow.steps == [{"name": "load", "state": "Ongoing"}]

    finalize_interrupted_subflow(step, "0:0:1", 0.0)

    assert json.loads(subflow_path.read_text(encoding="utf-8"))["steps"] == [
        {"name": "load", "state": "Incomplete", "runtime": "0:0:1", "peak memory (mb)": 0.0}
    ]


def test_worker_crash_does_not_trust_stale_success_result(monkeypatch, tmp_path):
    step = _workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    result_path.write_text(
        json.dumps({"attempt_id": "test-attempt", "done": True, "ok": True, "events": []})
    )
    fake = _FakePopen(poll_script=[-11])
    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", lambda *_args, **_kwargs: fake)

    result = execute_tool_step(_workspace(tmp_path), step, None)

    assert result.error is not None
    assert "code -11" in result.error
    assert not result_path.exists()


def test_worker_exit_without_result_is_a_failure(monkeypatch, tmp_path):
    step = _workspace_step(tmp_path)
    fake = _FakePopen(poll_script=[0])
    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", lambda *_args, **_kwargs: fake)

    result = execute_tool_step(_workspace(tmp_path), step, None)

    assert result.error is not None
    assert "code 0" in result.error


def test_success_result_with_nonzero_exit_is_a_failure(monkeypatch, tmp_path):
    step = _workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    monkeypatch.setattr(
        step_subprocess.worker.subprocess,
        "Popen",
        _spawn_with_result(result_path, {"done": True, "ok": True, "events": []}, returncode=-11),
    )

    result = execute_tool_step(_workspace(tmp_path), step, None)

    assert result.error is not None
    assert "code -11" in result.error


def test_mismatched_attempt_result_and_events_are_rejected(monkeypatch, tmp_path):
    step = _workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    monkeypatch.setattr(
        step_subprocess.worker.subprocess,
        "Popen",
        _spawn_with_result(
            result_path,
            {
                "attempt_id": "other-attempt",
                "done": True,
                "ok": True,
                "events": [{"type": "subflow_stage", "subflow_step": {"name": "stale"}}],
            },
        ),
    )
    replayed = []
    observer = _ns(on_subflow_stage=lambda _step, event: replayed.append(event))

    result = execute_tool_step(_workspace(tmp_path), step, None, observer=observer)

    assert result.error is not None
    assert "mismatched attempt id" in result.error
    assert replayed == []


def test_sequential_attempts_accept_only_their_own_results(monkeypatch, tmp_path):
    workspace = _workspace(tmp_path)
    step = _workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    attempt_ids = iter(["attempt-one", "attempt-two"])
    monkeypatch.setattr(step_subprocess, "new_attempt_id", lambda: next(attempt_ids))
    processes = []

    def spawn(*_args, **_kwargs):
        attempt_id = "attempt-one" if not processes else "attempt-two"
        process = _FakePopen(poll_script=[0])
        processes.append(process)
        result_path.write_text(
            json.dumps({"attempt_id": attempt_id, "done": True, "ok": True, "events": []})
        )
        _publish_response(result_path)
        return process

    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", spawn)

    first = execute_tool_step(workspace, step, None)
    second = execute_tool_step(workspace, step, None)

    payload_ids = [json.loads(process.stdin.getvalue())["attempt_id"] for process in processes]
    assert payload_ids == ["attempt-one", "attempt-two"]
    assert first.error is None
    assert second.error is None
    assert first.resource_observation is not None
    assert second.resource_observation is not None
    assert [
        first.resource_observation["attempt_id"],
        second.resource_observation["attempt_id"],
    ] == payload_ids


def test_execute_step_subprocess_reports_worker_failure_result(monkeypatch, tmp_path):
    step = _workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    monkeypatch.setattr(
        step_subprocess.worker.subprocess,
        "Popen",
        _spawn_with_result(
            result_path,
            {"done": True, "ok": False, "error": "boom", "events": []},
            returncode=1,
        ),
    )
    result = execute_tool_step(_workspace(tmp_path), step, None)

    assert result.error is not None
    assert "boom" in result.error


def test_execute_step_subprocess_succeeds_and_replays_events(monkeypatch, tmp_path):
    step = _workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    monkeypatch.setattr(
        step_subprocess.worker.subprocess,
        "Popen",
        _spawn_with_result(
            result_path,
            {
                "done": True,
                "ok": True,
                "error": None,
                "events": [
                    {
                        "type": "subflow_stage",
                        "subflow_step": {"name": "load", "state": "Ongoing"},
                    },
                    {"type": "subflow_stage", "subflow_step": {"name": "load", "state": "Success"}},
                ],
            },
        ),
    )

    replayed = []

    class Observer:
        def on_subflow_stage(self, workspace_step, subflow_step):
            replayed.append((workspace_step.name, subflow_step))

        def raise_if_cancelled(self):
            return None

    result = execute_tool_step(_workspace(tmp_path), step, None, observer=Observer())

    assert result.error is None
    assert [entry[1]["state"] for entry in replayed] == ["Ongoing", "Success"]


def test_execute_step_subprocess_cancel_replays_pending_events(monkeypatch, tmp_path):
    step = _workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME

    def spawn(*_args, **_kwargs):
        result_path.write_text(
            json.dumps(
                {
                    "attempt_id": "test-attempt",
                    "done": False,
                    "ok": False,
                    "events": [
                        {
                            "type": "subflow_stage",
                            "subflow_step": {"name": "load", "state": "Success"},
                        }
                    ],
                }
            )
        )
        return _FakePopen(poll_script=[None])

    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", spawn)
    replayed = []

    class Observer:
        def on_subflow_stage(self, _step, subflow_step):
            replayed.append(subflow_step)

        def raise_if_cancelled(self):
            raise RuntimeError("stop")

    result = execute_tool_step(_workspace(tmp_path), step, None, observer=Observer())

    assert result.error is not None
    assert "cancelled" in result.error
    assert replayed == [{"name": "load", "state": "Success"}]


def test_execute_step_subprocess_cancel_terminates_worker(monkeypatch, tmp_path):
    fake = _FakePopen(returncode=0, poll_script=[None, None, None])
    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", lambda *a, **k: fake)

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


@pytest.mark.parametrize("outcome", ["success", "crash", "cancel"])
def test_resource_observation_finishes_before_group_termination(monkeypatch, tmp_path, outcome):
    workspace = _workspace(tmp_path)
    step = _workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    if outcome == "success":
        popen = _spawn_with_result(result_path, {"done": True, "ok": True, "events": []})
    else:
        fake = _FakePopen(poll_script=[-11] if outcome == "crash" else [None])

        def popen(*_args, **_kwargs):
            return fake

    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", popen)
    calls = []
    monkeypatch.setattr(
        step_subprocess,
        "start_observation",
        lambda *_args, **_kwargs: _ns(finish=lambda: calls.append("resources") or {}),
    )

    def terminate(process):
        calls.append("terminate")
        _terminate_fake(process)

    monkeypatch.setattr(step_subprocess.worker, "terminate_process_group", terminate)
    observer = None
    if outcome == "cancel":

        def cancelled():
            raise RuntimeError("stop")

        observer = _ns(raise_if_cancelled=cancelled)

    result = step_subprocess.execute_step_subprocess(workspace, step, observer=observer)

    assert calls == ["resources", "terminate"]
    if outcome == "success":
        assert result.error is None
    else:
        assert result.error is not None


def test_resource_finalization_failure_still_terminates_worker(monkeypatch, tmp_path):
    step = _workspace_step(tmp_path)
    fake = _FakePopen(poll_script=[0])
    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", lambda *_args, **_kwargs: fake)

    def fail_finish():
        raise RuntimeError("observation failed")

    monkeypatch.setattr(
        step_subprocess,
        "start_observation",
        lambda *_args, **_kwargs: _ns(finish=fail_finish),
    )
    terminated = []
    monkeypatch.setattr(
        step_subprocess.worker,
        "terminate_process_group",
        lambda process: terminated.append(process),
    )

    with pytest.raises(RuntimeError, match="observation failed"):
        step_subprocess.execute_step_subprocess(_workspace(tmp_path), step)

    assert terminated == [fake]


def test_a_response_left_by_an_earlier_attempt_is_not_accepted(monkeypatch, tmp_path):
    step = _workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    monkeypatch.setattr(
        step_subprocess.worker.subprocess,
        "Popen",
        _spawn_with_result(result_path, {"done": True, "ok": True, "events": []}),
    )
    assert execute_tool_step(_workspace(tmp_path), step, None).error is None

    def spawn_without_response(*_args, **_kwargs):
        result_path.write_text(json.dumps({"attempt_id": "test-attempt", "done": True, "ok": True}))
        return _FakePopen(poll_script=[0])

    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", spawn_without_response)
    result = execute_tool_step(_workspace(tmp_path), step, None)

    assert result.error is not None
    assert "did not publish rsp.json" in result.error
