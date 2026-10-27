import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent.workspace_api as workspace_api
from agent.engine import AgentEngineFlow
from agent.operations import RuntimeOperationManager
from agent.requests import CandidateRerunRequest, CandidateResumeRequest
from chipcompiler.data import StateEnum, Workspace
from chipcompiler.data.parameter import Parameters, save_parameter
from chipcompiler.data.workspace import Flow, load_workspace
from chipcompiler.engine import EngineDB
from chipcompiler.engine.step_execution import StepExecutionResult
from chipcompiler.tools.ecc.module import ECCToolsModule

CONTEXT_SHA256 = "sha256:" + "a" * 64


class _EccApi:
    def __init__(self, workspace):
        self.session = SimpleNamespace(
            workspace=workspace,
            db_handle=None,
            workspace_revision=0,
        )
        self.events = []
        self.operations = RuntimeOperationManager(self.events.append)

    def _get_session(self, workspace_id):
        assert workspace_id == "workspace-1"
        return self.session

    @staticmethod
    def _validate_workspace_revision(session, expected_workspace_revision):
        actual = getattr(session, "workspace_revision", 0)
        if (
            expected_workspace_revision is not None
            and actual != 0
            and expected_workspace_revision != actual
        ):
            raise ValueError("workspace revision mismatch")

    def _load_workspace(self, directory):
        return load_workspace(directory)

    def _with_session_mutation_lock(self, workspace_id, operation):
        assert workspace_id == "workspace-1"
        return operation(self.session)

    def _should_capture_session_db(self, _session):
        return False

    def _close_transient_flow_db(self, _flow):
        return None


def _make_workspace(root, records, *, design="same-design"):
    (root / "home").mkdir(parents=True)
    (root / "log").mkdir()
    workspace = Workspace(directory=root, flow=Flow(path=root / "home" / "flow.json"))
    workspace.design.name = design
    workspace.design.top_module = design
    parameters = Parameters(
        path=root / "home" / "params.toml",
        data={"design": design, "top_module": design, "pdk": "ics55", "clock": "clk"},
    )
    assert save_parameter(parameters)
    workspace.parameters = parameters
    flow = AgentEngineFlow(workspace)
    workspace.flow.data = {
        "steps": [flow.init_flow_step(name, tool, state) for name, tool, state in records]
    }
    assert flow.save()
    if any(name == "place" for name, _tool, _state in records):
        config_path = root / "config" / "dreamplace_ecc.json"
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text(
            json.dumps({"target_density": 0.5, "random_seed": 17}), encoding="utf-8"
        )
    flow.create_step_workspaces(initialize_config=False)
    for step in flow.workspace_steps:
        if step.name == "Floorplan":
            _write_success_outputs(step)
    return workspace


def _rerun_request(candidate_id="candidate-1"):
    return CandidateRerunRequest(
        workspace_id="workspace-1",
        target_step="place",
        end_step="Harden",
        candidate_id=candidate_id,
        patch=[{"knob_id": "place.target_density", "value": 0.6}],
        execution_scope="full_flow",
        idempotency_key=f"execution.{candidate_id}",
        context_sha256=CONTEXT_SHA256,
        parameter_card_sha256=CONTEXT_SHA256,
        seed=17,
    )


def _resume_request():
    return CandidateResumeRequest(
        workspace_id="workspace-1",
        candidate_id="candidate-1",
        idempotency_key="execution.resume-1",
        context_sha256=CONTEXT_SHA256,
        parameter_card_sha256=CONTEXT_SHA256,
        seed=17,
    )


def _wait_for_terminal(operations, operation_id, expected_state):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        status = operations.operation_status(operation_id)
        if status["state"] in {"succeeded", "failed", "cancelled"}:
            assert status["state"] == expected_state, json.dumps(status, indent=2)
            return status
        time.sleep(0.01)
    raise AssertionError(f"operation {operation_id} did not reach a terminal state")


def _write_success_outputs(step):
    paths = [step.output.def_, step.output.verilog]
    if step.name == "Harden":
        paths.extend((step.output.gds, step.output.lef, step.output.lib))
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("valid", encoding="utf-8")
    manifest = step.output.geometry_manifest
    if manifest is not None:
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("{}", encoding="utf-8")
    if step.name == "place":
        report = step.directory / "analysis" / "parameter_runtime_report.v2.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            json.dumps(
                {
                    "schema_version": "tool.parameter_runtime_report.v2",
                    "knob_id": "place.target_density",
                    "written_value": 0.6,
                    "tool": {
                        "name": "DREAMPlace",
                        "revision": "candidate-test",
                        "source_sha256": "sha256:" + "0" * 64,
                    },
                    "actual_value": 0.6,
                    "status": "effective",
                    "reason": None,
                    "observation": {
                        "target_density": 0.6,
                        "density_operator_call_count": 1,
                    },
                }
            ),
            encoding="utf-8",
        )


def test_candidate_rerun_parent_has_no_native_db_or_stdio(monkeypatch, tmp_path):
    from chipcompiler.engine import step_execution

    api = workspace_api.FlowAgentRuntimeApi(
        _EccApi(
            _make_workspace(
                tmp_path / "source",
                [
                    ("Floorplan", "ecc", StateEnum.Success),
                    ("place", "dreamplace", StateEnum.Unstart),
                    ("Harden", "ecc", StateEnum.Unstart),
                ],
            )
        )
    )
    redirects = []
    monkeypatch.setattr(
        "chipcompiler.utility.log.redirect_stdio_to_file",
        lambda path: redirects.append(path),
    )

    def fail_native_init(*_args, **_kwargs):
        raise AssertionError("parent native DB initialization must not run")

    monkeypatch.setattr(EngineDB, "create_db_engine", fail_native_init)
    monkeypatch.setattr(ECCToolsModule, "__init__", fail_native_init)

    def fake_worker(_workspace, step, _engine_db, **_kwargs):
        _write_success_outputs(step)
        return StepExecutionResult(
            error=None, elapsed_seconds=0.0, peak_memory_mb=0.0, runtime="0:0:0"
        )

    monkeypatch.setattr(step_execution, "_execute_in_worker", fake_worker)

    started = api.candidate_rerun(_rerun_request())
    terminal = _wait_for_terminal(api.ecc_api.operations, started["operationId"], "succeeded")

    assert terminal["result"]["candidateId"] == "candidate-1"
    assert redirects == []


def _cancel_running_step(flow, started, release):
    def run_step(step, *, rerun, observer=None):
        assert observer is not None
        flow.set_state(step.name, step.tool, StateEnum.Ongoing)
        observer.on_step_started(step)
        started.set()
        assert release.wait(10)
        flow.set_state(step.name, step.tool, StateEnum.Imcomplete)
        observer.on_step_completed(step, StateEnum.Imcomplete, "cancel requested")
        return StateEnum.Imcomplete

    return run_step


def test_candidate_rerun_cancel_while_running_preserves_evidence(monkeypatch, tmp_path):
    api = workspace_api.FlowAgentRuntimeApi(
        _EccApi(
            _make_workspace(
                tmp_path / "source",
                [
                    ("Floorplan", "ecc", StateEnum.Success),
                    ("place", "dreamplace", StateEnum.Unstart),
                    ("Harden", "ecc", StateEnum.Unstart),
                ],
            )
        )
    )
    started, release = threading.Event(), threading.Event()
    original_build = workspace_api.build_agent_flow_for_workspace

    def build_flow(workspace, *, create_step_workspaces=True):
        flow = original_build(workspace, create_step_workspaces=create_step_workspaces)
        monkeypatch.setattr(flow, "run_step", _cancel_running_step(flow, started, release))
        return flow

    monkeypatch.setattr(workspace_api, "build_agent_flow_for_workspace", build_flow)

    started_operation = api.candidate_rerun(_rerun_request())
    operation_id = started_operation["operationId"]
    assert started.wait(10)
    assert api.ecc_api.operations.request_cancel(operation_id)["accepted"] is True
    release.set()
    terminal = _wait_for_terminal(api.ecc_api.operations, operation_id, "cancelled")

    assert terminal["result"]["candidateId"] == "candidate-1"
    candidate_flow = (
        tmp_path / "source" / ".agent" / "candidates" / "candidate-1" / "home" / "flow.json"
    )
    assert json.loads(candidate_flow.read_text())["steps"][1]["state"] == "Incomplete"


def test_candidate_resume_cancel_while_running_preserves_evidence(monkeypatch, tmp_path):
    candidate = tmp_path / ".agent" / "candidates" / "candidate-1"
    workspace = _make_workspace(
        candidate,
        [
            ("place", "dreamplace", StateEnum.Success),
            ("route", "ecc", StateEnum.Imcomplete),
            ("Harden", "ecc", StateEnum.Unstart),
        ],
    )
    flow = AgentEngineFlow(workspace)
    started, release = threading.Event(), threading.Event()
    monkeypatch.setattr(flow, "run_step", _cancel_running_step(flow, started, release))
    parent = {
        "root_ref": None,
        "manifest_ref": None,
        "manifest_sha256": None,
        "flow_sha256": "sha256:" + "1" * 64,
        "state_sha256": "sha256:" + "2" * 64,
    }
    manifest = {"target_step": "place", "parent_candidate_root_ref": None}
    api = workspace_api.FlowAgentRuntimeApi(_EccApi(SimpleNamespace(directory=tmp_path)))
    monkeypatch.setattr(
        "agent.candidate_resume._load_candidate_resume",
        lambda *_args: (workspace, manifest, parent),
    )
    monkeypatch.setattr(api, "_build_flow", lambda *_args, **_kwargs: flow)
    monkeypatch.setattr(
        "agent.candidate_resume._validate_candidate_resume_binding", lambda *_args: []
    )

    started_operation = api.candidate_resume(_resume_request())
    operation_id = started_operation["operationId"]
    assert started.wait(10)
    assert api.ecc_api.operations.request_cancel(operation_id)["accepted"] is True
    release.set()
    terminal = _wait_for_terminal(api.ecc_api.operations, operation_id, "cancelled")

    assert terminal["result"]["candidateId"] == "candidate-1"
    assert terminal["result"]["resumeStep"] == "route"
    assert (
        json.loads((candidate / "home" / "flow.json").read_text())["steps"][1]["state"]
        == "Incomplete"
    )


def _worker_sitecustomize_source():
    return """
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

from agent import tools as agent_tools
from chipcompiler.engine.flow import EngineFlow


def initialize_db(flow, step):
    flow.engine_db = SimpleNamespace(engine=None, initialization_error=None)
    return True

EngineFlow.init_db_engine_for_step = initialize_db


def write_outputs(step):
    paths = [step.output.def_, step.output.verilog]
    if step.name == "Harden":
        paths.extend((step.output.gds, step.output.lef, step.output.lib))
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("valid", encoding="utf-8")
    manifest = step.output.geometry_manifest
    if manifest is not None:
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("{}", encoding="utf-8")
    if step.name == "place":
        report = step.directory / "analysis" / "parameter_runtime_report.v2.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            json.dumps(
                {
                    "schema_version": "tool.parameter_runtime_report.v2",
                    "knob_id": "place.target_density",
                    "written_value": 0.6,
                    "tool": {
                        "name": "DREAMPlace",
                        "revision": "candidate-test",
                        "source_sha256": "sha256:" + "0" * 64,
                    },
                    "actual_value": 0.6,
                    "status": "effective",
                    "reason": None,
                    "observation": {
                        "target_density": 0.6,
                        "density_operator_call_count": 1,
                    },
                }
            ),
            encoding="utf-8",
        )


def run_step(workspace, step, ecc_module=None):
    candidate = Path(workspace.directory).name
    mode = os.environ.get("WORKER_TEST_MODE")
    if mode == "sleep" and step.name == "place":
        Path(os.environ["WORKER_TEST_PID_PATH"]).write_text(str(os.getpid()))
        time.sleep(60)
    if mode == "barrier" and step.name == "place":
        ready_dir = Path(os.environ["WORKER_TEST_READY_DIR"])
        (ready_dir / f"{candidate}.ready").write_text("ready", encoding="utf-8")
        deadline = time.monotonic() + 20
        while len(list(ready_dir.glob("*.ready"))) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        if len(list(ready_dir.glob("*.ready"))) != 2:
            raise RuntimeError("candidate workers did not overlap")
    print(f"step-marker-{candidate}")
    write_outputs(step)
    return True

agent_tools.load_eda_module = lambda *_args, **_kwargs: SimpleNamespace(
    build_step_config=lambda *_args: None,
    run_step=run_step,
)
agent_tools.log_workspace_step = lambda *_args, **_kwargs: None
"""


def _configure_worker_test(monkeypatch, tmp_path, mode, **values):
    site_dir = tmp_path / "worker-startup"
    site_dir.mkdir()
    (site_dir / "sitecustomize.py").write_text(_worker_sitecustomize_source(), encoding="utf-8")
    repository = Path(__file__).parents[2]
    monkeypatch.setenv("WORKER_TEST_MODE", mode)
    for name, value in values.items():
        monkeypatch.setenv(name, str(value))
    monkeypatch.setenv(
        "PYTHONPATH",
        os.pathsep.join([str(site_dir), str(repository), os.environ.get("PYTHONPATH", "")]),
    )


def _wait_for_path(path):
    deadline = time.monotonic() + 20
    while not path.is_file() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert path.is_file(), f"timed out waiting for {path}"


@pytest.mark.real_step_worker
def test_sigkill_step_worker_fails_candidate_with_evidence(monkeypatch, tmp_path):
    api = workspace_api.FlowAgentRuntimeApi(
        _EccApi(
            _make_workspace(
                tmp_path / "source",
                [
                    ("Floorplan", "ecc", StateEnum.Success),
                    ("place", "dreamplace", StateEnum.Unstart),
                    ("Harden", "ecc", StateEnum.Unstart),
                ],
            )
        )
    )
    worker_pid_path = tmp_path / "step-worker.pid"
    _configure_worker_test(
        monkeypatch,
        tmp_path,
        "sleep",
        WORKER_TEST_PID_PATH=worker_pid_path,
    )
    started = api.candidate_rerun(_rerun_request())
    operation_id = started["operationId"]
    _wait_for_path(worker_pid_path)

    os.kill(int(worker_pid_path.read_text()), 9)

    terminal = _wait_for_terminal(api.ecc_api.operations, operation_id, "failed")
    assert terminal["result"]["candidateId"] == "candidate-1"
    candidate_flow = (
        tmp_path / "source" / ".agent" / "candidates" / "candidate-1" / "home" / "flow.json"
    )
    assert json.loads(candidate_flow.read_text())["steps"][1]["state"] == "Incomplete"
    assert api.ecc_api.operations.operation_status(operation_id) == terminal


@pytest.mark.real_step_worker
def test_same_design_candidates_keep_logs_and_events_separate(monkeypatch, tmp_path):
    api = workspace_api.FlowAgentRuntimeApi(
        _EccApi(
            _make_workspace(
                tmp_path / "source",
                [
                    ("Floorplan", "ecc", StateEnum.Success),
                    ("place", "dreamplace", StateEnum.Unstart),
                    ("Harden", "ecc", StateEnum.Unstart),
                ],
            )
        )
    )
    ready_dir = tmp_path / "ready"
    ready_dir.mkdir()
    _configure_worker_test(
        monkeypatch,
        tmp_path,
        "barrier",
        WORKER_TEST_READY_DIR=ready_dir,
    )
    original_build = workspace_api.build_agent_flow_for_workspace

    def build_flow(workspace, *, create_step_workspaces=True):
        workspace.logger.info("workspace-marker-%s", Path(workspace.directory).name)
        return original_build(workspace, create_step_workspaces=create_step_workspaces)

    monkeypatch.setattr(workspace_api, "build_agent_flow_for_workspace", build_flow)

    first = api.candidate_rerun(_rerun_request("candidate-1"))
    second = api.candidate_rerun(_rerun_request("candidate-2"))
    first_terminal = _wait_for_terminal(api.ecc_api.operations, first["operationId"], "succeeded")
    second_terminal = _wait_for_terminal(api.ecc_api.operations, second["operationId"], "succeeded")

    for candidate_id, operation_id, terminal in (
        ("candidate-1", first["operationId"], first_terminal),
        ("candidate-2", second["operationId"], second_terminal),
    ):
        other_id = "candidate-2" if candidate_id == "candidate-1" else "candidate-1"
        candidate_root = tmp_path / "source" / ".agent" / "candidates" / candidate_id
        step_log = candidate_root / "place_dreamplace" / "log" / "place.log"
        step_text = step_log.read_text(encoding="utf-8", errors="replace")
        assert f"step-marker-{candidate_id}" in step_text
        assert f"step-marker-{other_id}" not in step_text
        workspace_text = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in (candidate_root / "log").iterdir()
            if path.is_file()
        )
        assert f"workspace-marker-{candidate_id}" in workspace_text
        assert f"workspace-marker-{other_id}" not in workspace_text
        assert terminal["result"]["candidateId"] == candidate_id
        events = [event for event in api.ecc_api.events if event["operationId"] == operation_id]
        assert events
        expected_workspace = f"workspace-1::candidate::{candidate_id}"
        assert all(event["workspaceId"] == expected_workspace for event in events)
