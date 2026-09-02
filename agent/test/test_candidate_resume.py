import json
import threading
from types import SimpleNamespace

import pytest

from agent.candidate_resume import (
    _candidate_resume_steps,
    _validate_candidate_resume_binding,
    _validate_candidate_resume_manifest,
)
from agent.data.candidate_artifacts import sha256_path
from agent.data.candidate_materialization import materialize_candidate_config
from agent.requests import CandidateResumeRequest
from agent.workspace_api import FlowAgentRuntimeApi, _workspace_state_sha256
from chipcompiler.runtime.operations import RuntimeOperationManager
from chipcompiler.runtime.workspace_api import RuntimeApiError

CONTEXT_SHA256 = "sha256:" + "a" * 64


def test_candidate_resume_slice_starts_at_first_non_success_step() -> None:
    records = [
        {"name": "place", "tool": "dreamplace", "state": "Success"},
        {"name": "CTS", "tool": "ecc", "state": "Incomplete"},
        {"name": "Harden", "tool": "ecc", "state": "Unstart"},
    ]
    steps = tuple(SimpleNamespace(name=item["name"], tool=item["tool"]) for item in records)
    flow = SimpleNamespace(
        workspace_steps=steps,
        get_step=lambda name, tool: next(
            item for item in records if item["name"] == name and item["tool"] == tool
        ),
    )

    resumed = _candidate_resume_steps(flow, "place")

    assert [step.name for step in resumed] == ["CTS", "Harden"]


def test_candidate_resume_runs_in_place_and_preserves_successful_target_artifacts(
    monkeypatch, tmp_path
) -> None:
    candidate_id = "candidate-1"
    candidate = tmp_path / ".agent" / "candidates" / candidate_id
    flow_data = {
        "steps": [
            {"name": "place", "tool": "dreamplace", "state": "Success"},
            {"name": "CTS", "tool": "ecc", "state": "Incomplete"},
            {"name": "Harden", "tool": "ecc", "state": "Unstart"},
        ]
    }
    flow_path = candidate / "home" / "flow.json"
    flow_path.parent.mkdir(parents=True)
    flow_path.write_text(json.dumps(flow_data), encoding="utf-8")
    config = candidate / "config" / "dreamplace.json"
    config.parent.mkdir()
    config.write_text('{"random_seed": 17}', encoding="utf-8")
    workspace = SimpleNamespace(
        directory=candidate,
        config={"dreamplace": config},
        flow=SimpleNamespace(data=flow_data, path=flow_path),
    )
    target_output = candidate / "place_dreamplace" / "output"
    cts_output = candidate / "CTS_ecc" / "output"
    harden_output = candidate / "Harden_ecc" / "output"
    for directory in (target_output, cts_output, harden_output):
        directory.mkdir(parents=True)
        (directory / "existing").write_text("evidence", encoding="utf-8")
    steps = (
        SimpleNamespace(name="place", tool="dreamplace", output={"dir": target_output}),
        SimpleNamespace(name="CTS", tool="ecc", output={"dir": cts_output}),
        SimpleNamespace(name="Harden", tool="ecc", output={"dir": harden_output}),
    )
    flow = _Flow(workspace, steps)
    parent = {
        "root_ref": None,
        "manifest_ref": None,
        "manifest_sha256": None,
        "flow_sha256": "sha256:" + "1" * 64,
        "state_sha256": "sha256:" + "2" * 64,
    }
    manifest = {"target_step": "place", "parent_candidate_root_ref": None}
    api = FlowAgentRuntimeApi(_EccApi(SimpleNamespace(directory=tmp_path)))
    monkeypatch.setattr(
        "agent.candidate_resume._load_candidate_resume",
        lambda *_args: (workspace, manifest, parent),
    )
    monkeypatch.setattr(api, "_build_flow", lambda *_args, **_kwargs: flow)
    monkeypatch.setattr(
        "agent.candidate_resume._validate_candidate_resume_binding",
        lambda *_args: [{"knob_id": "place.target_density", "value": 0.6}],
    )
    run_steps = []
    monkeypatch.setattr(
        "agent.candidate_resume._run_candidate_step",
        lambda _flow, step, **_kwargs: run_steps.append(step.name),
    )
    monkeypatch.setattr(
        "agent.candidate_resume._candidate_rerun_result",
        lambda *_args, **_kwargs: {"candidateId": candidate_id},
    )

    started = api.candidate_resume(
        CandidateResumeRequest(
            workspace_id="workspace-1",
            candidate_id=candidate_id,
            idempotency_key="episode-1.resume-1",
            context_sha256=CONTEXT_SHA256,
            seed=17,
        )
    )
    terminal = _wait_for_terminal(api.ecc_api.operations, started["operationId"])

    assert terminal["result"] == {"candidateId": candidate_id, "resumeStep": "CTS"}
    assert run_steps == ["CTS", "Harden"]
    assert (target_output / "existing").is_file()
    assert not (cts_output / "existing").exists()
    assert not (harden_output / "existing").exists()


def test_candidate_resume_manifest_rejects_illegal_state_missing_receipt_and_state_drift(
    tmp_path,
) -> None:
    candidate_id = "candidate-1"
    candidate_ref = f".agent/candidates/{candidate_id}"
    candidate = tmp_path / candidate_ref
    flow = candidate / "home" / "flow.json"
    flow.parent.mkdir(parents=True)
    flow.write_text('{"steps": []}', encoding="utf-8")
    config = candidate / "config" / "dreamplace.json"
    config.parent.mkdir()
    config.write_text('{"random_seed": 17}', encoding="utf-8")
    analysis = candidate / "analysis"
    analysis.mkdir()
    materialization = analysis / "candidate_materialization.v1.json"
    input_binding = analysis / "candidate_input_binding.v1.json"
    materialization.write_text("{}", encoding="utf-8")
    input_binding.write_text("{}", encoding="utf-8")
    manifest = {
        "schema": "ecc.workspace.candidate_workspace.v1",
        "schema_version": 1,
        "candidate_id": candidate_id,
        "candidate_root_ref": candidate_ref,
        "terminal_state": "failed",
        "target_step": "place",
        "end_step": "Harden",
        "execution_scope": "full_flow",
        "candidate_flow_sha256": sha256_path(flow),
        "candidate_state_sha256": _workspace_state_sha256(candidate),
        "artifacts": {
            "candidate_materialization": {
                "ref": "analysis/candidate_materialization.v1.json",
                "sha256": sha256_path(materialization),
            },
            "candidate_input_binding": {
                "ref": "analysis/candidate_input_binding.v1.json",
                "sha256": sha256_path(input_binding),
            },
        },
    }
    _validate_candidate_resume_manifest(tmp_path, candidate, candidate_ref, manifest)

    with pytest.raises(RuntimeApiError, match="manifest binding"):
        _validate_candidate_resume_manifest(
            tmp_path, candidate, candidate_ref, {**manifest, "terminal_state": "succeeded"}
        )

    input_binding.unlink()
    with pytest.raises(RuntimeApiError, match="missing or unsafe"):
        _validate_candidate_resume_manifest(tmp_path, candidate, candidate_ref, manifest)
    input_binding.write_text("{}", encoding="utf-8")

    config.write_text('{"random_seed": 18}', encoding="utf-8")
    with pytest.raises(RuntimeApiError, match="manifest binding"):
        _validate_candidate_resume_manifest(tmp_path, candidate, candidate_ref, manifest)


def test_candidate_resume_restores_drifted_target_config_before_strict_validation(
    monkeypatch, tmp_path
) -> None:
    config = tmp_path / "config" / "dreamplace.json"
    config.parent.mkdir()
    config.write_text('{"random_seed": 17, "target_density": 0.5}', encoding="utf-8")
    workspace = SimpleNamespace(
        directory=tmp_path,
        config={"dreamplace": config},
        flow=SimpleNamespace(data={"steps": [{"name": "place", "tool": "dreamplace"}]}),
    )
    materialize_candidate_config(
        workspace,
        "place",
        [{"knob_id": "place.target_density", "value": 0.6}],
        "candidate-1",
    )
    config.write_text('{"random_seed": 17, "target_density": 0.9}', encoding="utf-8")
    monkeypatch.setattr("agent.candidate_resume._reapply_candidate_input", lambda *_args: None)

    with pytest.raises(RuntimeApiError, match="seed binding"):
        _validate_candidate_resume_binding(
            workspace,
            SimpleNamespace(),
            {"target_step": "place", "artifacts": {}},
            CandidateResumeRequest(
                workspace_id="workspace-1",
                candidate_id="candidate-1",
                idempotency_key="episode-1.resume-invalid",
                context_sha256=CONTEXT_SHA256,
                seed=18,
            ),
        )
    assert json.loads(config.read_text(encoding="utf-8"))["target_density"] == 0.9

    patch = _validate_candidate_resume_binding(
        workspace,
        SimpleNamespace(),
        {"target_step": "place", "artifacts": {}},
        CandidateResumeRequest(
            workspace_id="workspace-1",
            candidate_id="candidate-1",
            idempotency_key="episode-1.resume-1",
            context_sha256=CONTEXT_SHA256,
            seed=17,
        ),
    )

    assert patch == [{"knob_id": "place.target_density", "value": 0.6}]
    assert json.loads(config.read_text(encoding="utf-8"))["target_density"] == 0.6


class _EccApi:
    def __init__(self, workspace):
        self.session = SimpleNamespace(workspace=workspace, db_handle=None)
        self.events = []
        self.operations = RuntimeOperationManager(self.events.append)

    def _get_session(self, workspace_id):
        assert workspace_id == "workspace-1"
        return self.session

    def _with_session_mutation_lock(self, workspace_id, operation):
        assert workspace_id == "workspace-1"
        return operation(self.session)

    def _close_transient_flow_db(self, _flow):
        return None


class _Flow:
    def __init__(self, workspace, workspace_steps):
        self.workspace = workspace
        self._workspace_steps = workspace_steps
        self.workspace_steps = ()
        self.initialize_config = None

    def create_step_workspaces(self, *, initialize_config=True):
        self.workspace_steps = self._workspace_steps
        self.initialize_config = initialize_config

    def get_step(self, name, tool):
        return next(
            (
                step
                for step in self.workspace.flow.data["steps"]
                if step["name"] == name and step["tool"] == tool
            ),
            None,
        )

    def save(self):
        self.workspace.flow.path.write_text(json.dumps(self.workspace.flow.data), encoding="utf-8")
        return True


def _wait_for_terminal(operations, operation_id):
    deadline = threading.Event()
    for _ in range(100):
        status = operations.operation_status(operation_id)
        if status["state"] in {"succeeded", "failed", "cancelled"}:
            assert status["state"] == "succeeded"
            return status
        deadline.wait(0.01)
    raise AssertionError("candidate operation did not reach a terminal state")
