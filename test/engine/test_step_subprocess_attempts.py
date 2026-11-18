"""Which worker attempts the parent accepts: crashes, cancellation, stale results."""

import json
from pathlib import Path

import pytest

from chipcompiler.engine import step_subprocess
from chipcompiler.engine.step_execution import execute_tool_step
from test.engine import step_worker_fakes as fakes

pytestmark = pytest.mark.real_step_worker


@pytest.fixture(autouse=True)
def _stub_worker_process(monkeypatch):
    fakes.stub_worker_process(monkeypatch)


def test_execute_step_subprocess_reports_worker_crash(monkeypatch, tmp_path):
    fake = fakes.FakePopen(returncode=-11)
    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", lambda *a, **k: fake)
    step = fakes.workspace_step(tmp_path)
    result = execute_tool_step(fakes.workspace(tmp_path), step, None)

    from chipcompiler.data.handshake import load_request

    payload = json.loads(fake.stdin.getvalue())
    request = load_request(Path(step.directory))
    assert {key: payload[key] for key in ("step_directory", "attempt_id")} == {
        "step_directory": str(request.directory),
        "attempt_id": "test-attempt",
    }
    assert (request.step, request.tool, request.layout_image) == ("placement", "ecc", True)
    assert payload["result_path"].endswith(step_subprocess._RESULT_NAME)
    assert result.error is not None
    assert "code -11" in result.error


def test_failed_worker_reloads_subflow_for_interrupted_finalization(monkeypatch, tmp_path):
    from chipcompiler.data import StateEnum, SubflowState
    from chipcompiler.engine.flow_completion import finalize_interrupted_subflow

    step = fakes.workspace_step(tmp_path)
    subflow_path = tmp_path / "subflow.json"
    step.subflow = SubflowState(path=subflow_path, steps=[])
    subflow_path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "path": str(subflow_path),
                "steps": [{"name": "load", "state": StateEnum.Ongoing.value}],
            }
        ),
        encoding="utf-8",
    )
    fake = fakes.FakePopen(poll_script=[-11])
    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", lambda *_args, **_kwargs: fake)

    result = execute_tool_step(fakes.workspace(tmp_path), step, None)

    assert result.error is not None
    assert "code -11" in result.error
    assert step.subflow.steps == [{"name": "load", "state": "Ongoing"}]

    finalize_interrupted_subflow(step, "0:0:1", 0.0)

    assert json.loads(subflow_path.read_text(encoding="utf-8"))["steps"] == [
        {"name": "load", "state": "Incomplete", "runtime": "0:0:1", "peak memory (mb)": 0.0}
    ]


def test_worker_crash_does_not_trust_stale_success_result(monkeypatch, tmp_path):
    step = fakes.workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    result_path.write_text(
        json.dumps({"attempt_id": "test-attempt", "done": True, "ok": True, "events": []})
    )
    fake = fakes.FakePopen(poll_script=[-11])
    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", lambda *_args, **_kwargs: fake)

    result = execute_tool_step(fakes.workspace(tmp_path), step, None)

    assert result.error is not None
    assert "code -11" in result.error
    assert not result_path.exists()


def test_worker_exit_without_result_is_a_failure(monkeypatch, tmp_path):
    step = fakes.workspace_step(tmp_path)
    fake = fakes.FakePopen(poll_script=[0])
    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", lambda *_args, **_kwargs: fake)

    result = execute_tool_step(fakes.workspace(tmp_path), step, None)

    assert result.error is not None
    assert "code 0" in result.error


def test_success_result_with_nonzero_exit_is_a_failure(monkeypatch, tmp_path):
    step = fakes.workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    monkeypatch.setattr(
        step_subprocess.worker.subprocess,
        "Popen",
        fakes.spawn_with_result(
            result_path, {"done": True, "ok": True, "events": []}, returncode=-11
        ),
    )

    result = execute_tool_step(fakes.workspace(tmp_path), step, None)

    assert result.error is not None
    assert "code -11" in result.error


def test_mismatched_attempt_result_and_events_are_rejected(monkeypatch, tmp_path):
    step = fakes.workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    monkeypatch.setattr(
        step_subprocess.worker.subprocess,
        "Popen",
        fakes.spawn_with_result(
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
    observer = fakes.ns(on_subflow_stage=lambda _step, event: replayed.append(event))

    result = execute_tool_step(fakes.workspace(tmp_path), step, None, observer=observer)

    assert result.error is not None
    assert "mismatched attempt id" in result.error
    assert replayed == []


def test_sequential_attempts_accept_only_their_own_results(monkeypatch, tmp_path):
    workspace = fakes.workspace(tmp_path)
    step = fakes.workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    attempt_ids = iter(["attempt-one", "attempt-two"])
    monkeypatch.setattr(step_subprocess, "new_attempt_id", lambda: next(attempt_ids))
    processes = []

    def spawn(*_args, **_kwargs):
        attempt_id = "attempt-one" if not processes else "attempt-two"
        process = fakes.FakePopen(poll_script=[0])
        processes.append(process)
        result_path.write_text(
            json.dumps({"attempt_id": attempt_id, "done": True, "ok": True, "events": []})
        )
        fakes.publish_response(result_path)
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
    step = fakes.workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    monkeypatch.setattr(
        step_subprocess.worker.subprocess,
        "Popen",
        fakes.spawn_with_result(
            result_path,
            {"done": True, "ok": False, "error": "boom", "events": []},
            returncode=1,
        ),
    )
    result = execute_tool_step(fakes.workspace(tmp_path), step, None)

    assert result.error is not None
    assert "boom" in result.error


def test_execute_step_subprocess_succeeds_and_replays_events(monkeypatch, tmp_path):
    step = fakes.workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    monkeypatch.setattr(
        step_subprocess.worker.subprocess,
        "Popen",
        fakes.spawn_with_result(
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

    result = execute_tool_step(fakes.workspace(tmp_path), step, None, observer=Observer())

    assert result.error is None
    assert [entry[1]["state"] for entry in replayed] == ["Ongoing", "Success"]


def test_execute_step_subprocess_cancel_replays_pending_events(monkeypatch, tmp_path):
    step = fakes.workspace_step(tmp_path)
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
        return fakes.FakePopen(poll_script=[None])

    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", spawn)
    replayed = []

    class Observer:
        def on_subflow_stage(self, _step, subflow_step):
            replayed.append(subflow_step)

        def raise_if_cancelled(self):
            raise RuntimeError("stop")

    result = execute_tool_step(fakes.workspace(tmp_path), step, None, observer=Observer())

    assert result.error is not None
    assert "cancelled" in result.error
    assert replayed == [{"name": "load", "state": "Success"}]


def test_execute_step_subprocess_cancel_terminates_worker(monkeypatch, tmp_path):
    fake = fakes.FakePopen(returncode=0, poll_script=[None, None, None])
    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", lambda *a, **k: fake)

    class Cancelled(RuntimeError):
        pass

    class Observer:
        calls = 0

        def raise_if_cancelled(self):
            Observer.calls += 1
            if Observer.calls >= 2:
                raise Cancelled("stop")

    step = fakes.workspace_step(tmp_path)
    result = execute_tool_step(fakes.workspace(tmp_path), step, None, observer=Observer())

    assert fake.terminated
    assert result.error is not None
    assert "cancelled" in result.error


@pytest.mark.parametrize("outcome", ["success", "crash", "cancel"])
def test_resource_observation_finishes_before_group_termination(monkeypatch, tmp_path, outcome):
    workspace = fakes.workspace(tmp_path)
    step = fakes.workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    if outcome == "success":
        popen = fakes.spawn_with_result(result_path, {"done": True, "ok": True, "events": []})
    else:
        fake = fakes.FakePopen(poll_script=[-11] if outcome == "crash" else [None])

        def popen(*_args, **_kwargs):
            return fake

    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", popen)
    calls = []
    monkeypatch.setattr(
        step_subprocess,
        "start_observation",
        lambda *_args, **_kwargs: fakes.ns(finish=lambda: calls.append("resources") or {}),
    )

    def terminate(process):
        calls.append("terminate")
        fakes.terminate_fake(process)

    monkeypatch.setattr(step_subprocess.worker, "terminate_process_group", terminate)
    observer = None
    if outcome == "cancel":

        def cancelled():
            raise RuntimeError("stop")

        observer = fakes.ns(raise_if_cancelled=cancelled)

    result = step_subprocess.execute_step_subprocess(workspace, step, observer=observer)

    assert calls == ["resources", "terminate"]
    if outcome == "success":
        assert result.error is None
    else:
        assert result.error is not None


def test_resource_finalization_failure_still_terminates_worker(monkeypatch, tmp_path):
    step = fakes.workspace_step(tmp_path)
    fake = fakes.FakePopen(poll_script=[0])
    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", lambda *_args, **_kwargs: fake)

    def fail_finish():
        raise RuntimeError("observation failed")

    monkeypatch.setattr(
        step_subprocess,
        "start_observation",
        lambda *_args, **_kwargs: fakes.ns(finish=fail_finish),
    )
    terminated = []
    monkeypatch.setattr(
        step_subprocess.worker,
        "terminate_process_group",
        lambda process: terminated.append(process),
    )

    with pytest.raises(RuntimeError, match="observation failed"):
        step_subprocess.execute_step_subprocess(fakes.workspace(tmp_path), step)

    assert terminated == [fake]


def test_a_response_left_by_an_earlier_attempt_is_not_accepted(monkeypatch, tmp_path):
    step = fakes.workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    monkeypatch.setattr(
        step_subprocess.worker.subprocess,
        "Popen",
        fakes.spawn_with_result(result_path, {"done": True, "ok": True, "events": []}),
    )
    assert execute_tool_step(fakes.workspace(tmp_path), step, None).error is None

    def spawn_without_response(*_args, **_kwargs):
        result_path.write_text(json.dumps({"attempt_id": "test-attempt", "done": True, "ok": True}))
        return fakes.FakePopen(poll_script=[0])

    monkeypatch.setattr(step_subprocess.worker.subprocess, "Popen", spawn_without_response)
    result = execute_tool_step(fakes.workspace(tmp_path), step, None)

    assert result.error is not None
    assert "did not publish rsp.json" in result.error


def test_a_failed_response_is_a_failure_even_when_the_worker_reports_ok(monkeypatch, tmp_path):
    from chipcompiler.data.handshake import ResponseStatus

    step = fakes.workspace_step(tmp_path)
    result_path = Path(step.log.file).parent / step_subprocess._RESULT_NAME
    monkeypatch.setattr(
        step_subprocess.worker.subprocess,
        "Popen",
        fakes.spawn_with_result(
            result_path, {"done": True, "ok": True, "events": []}, status=ResponseStatus.FAILED
        ),
    )

    result = execute_tool_step(fakes.workspace(tmp_path), step, None)

    assert result.error == "placement(ecc) did not produce the required outputs."
