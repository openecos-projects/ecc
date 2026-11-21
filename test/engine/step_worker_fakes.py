"""Fake worker processes for the parent side of the step subprocess tests."""

import io
import json
import logging
from types import SimpleNamespace
from typing import Any

from chipcompiler.data.handshake import ResponseStatus
from chipcompiler.engine.step import process as step_subprocess


def terminate_fake(process):
    if process.poll() is None:
        process.terminate()
    process.wait()


def ns(**kwargs: object) -> Any:
    return SimpleNamespace(**kwargs)


def stub_worker_process(monkeypatch) -> None:
    # main() runs in the pytest process here; arming PR_SET_PDEATHSIG would
    # SIGKILL the runner when the recorded parent pid is not our ppid.
    monkeypatch.setattr(step_subprocess.worker, "arm_parent_death_signal", lambda parent_pid: None)
    monkeypatch.setattr(step_subprocess.worker, "_start_parent_death_watchdog", lambda: None)
    monkeypatch.setattr(step_subprocess.worker, "terminate_process_group", terminate_fake)
    monkeypatch.setattr(step_subprocess, "new_attempt_id", lambda: "test-attempt")


def workspace_step(tmp_path, name="placement", tool="ecc"):
    from chipcompiler.data import StepInput

    log_file = tmp_path / "log" / "step.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    return ns(
        name=name,
        tool=tool,
        directory=str(tmp_path / f"{name}_{tool}"),
        input=StepInput(),
        log=ns(file=str(log_file)),
    )


def workspace(tmp_path):
    from chipcompiler.data.parameter import Parameters, save_parameter
    from chipcompiler.data.workspace import Flow

    parameters = Parameters(
        path=tmp_path / "home/params.toml",
        data={"design": "example", "top_module": "example", "pdk": "ics55", "clock": "clk"},
    )
    assert save_parameter(parameters)
    return ns(
        directory=tmp_path,
        logger=logging.getLogger("ecc-test"),
        parameters=parameters,
        flow=Flow(path=tmp_path / "home/flow.json", data={"schema_version": 3, "steps": []}),
    )


class FakeStdin(io.BytesIO):
    def close(self):
        # keep the buffer readable so tests can assert the payload
        pass


class FakePopen:
    """Minimal subprocess.Popen stand-in driven by a poll script."""

    def __init__(self, returncode=0, poll_script=None):
        self.pid = 4321
        self.returncode = None
        self.stdin = FakeStdin()
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


def publish_response(result_path, *, parasitics=(), status=ResponseStatus.SUCCESS):
    """Write the rsp.json the worker publishes for the request the parent wrote."""
    from chipcompiler.data.handshake import (
        DesignFiles,
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
            status=status,
            design=DesignFiles(),
            design_states=frozenset(),
            outputs={AnalysisData.PARASITICS: tuple(parasitics)} if parasitics else {},
            design_source=request.design_source,
            upstream=request.upstream,
            warnings=frozenset(),
        ),
    )


def spawn_with_result(
    result_path, result, *, returncode=0, parasitics=(), status=ResponseStatus.SUCCESS
):
    def spawn(*_args, **_kwargs):
        result_path.write_text(json.dumps({"attempt_id": "test-attempt", **result}))
        if result.get("done"):
            publish_response(result_path, parasitics=parasitics, status=status)
        return FakePopen(poll_script=[returncode])

    return spawn
