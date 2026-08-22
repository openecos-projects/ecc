import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.requests import CandidateRerunRequest
from agent.workspace_api import FlowAgentRuntimeApi, _candidate_step_artifact_dirs
from chipcompiler.data import StateEnum
from chipcompiler.data.workspace.layout import EccOutput
from chipcompiler.runtime.operations import RuntimeOperationManager
from chipcompiler.runtime.workspace_api import RuntimeApiError


def test_candidate_artifact_dirs_support_typed_step_outputs(tmp_path):
    output_dir = tmp_path / "place_dreamplace" / "output"
    analysis_dir = tmp_path / "place_dreamplace" / "analysis"
    step = SimpleNamespace(
        output=EccOutput(dir=output_dir),
        analysis={"dir": analysis_dir},
    )

    assert _candidate_step_artifact_dirs(step) == (Path(output_dir), Path(analysis_dir))


def test_candidate_rerun_starts_a_full_flow_operation_and_replays_its_receipts(
    monkeypatch, tmp_path
):
    workspace = SimpleNamespace(
        directory=tmp_path,
        flow=SimpleNamespace(
            data={
                "steps": [
                    {"name": "Floorplan", "tool": "ecc", "state": "Success"},
                    {"name": "place", "tool": "dreamplace", "state": "Success"},
                    {"name": "CTS", "tool": "ecc", "state": "Success"},
                ]
            }
        ),
    )
    place_output = tmp_path / "place_dreamplace" / "output"
    place_analysis = tmp_path / "place_dreamplace" / "analysis"
    cts_output = tmp_path / "CTS_ecc" / "output"
    for directory in (place_output, place_analysis, cts_output):
        directory.mkdir(parents=True)
        (directory / "stale").write_text("stale", encoding="utf-8")
    flow = _Flow(
        workspace,
        (
            SimpleNamespace(name="Floorplan", tool="ecc", output={}),
            SimpleNamespace(
                name="place",
                tool="dreamplace",
                output=EccOutput(dir=place_output),
                analysis={"dir": place_analysis},
            ),
            SimpleNamespace(name="CTS", tool="ecc", output={"dir": cts_output}),
        ),
    )
    api = FlowAgentRuntimeApi(_EccApi(workspace))
    calls = []
    monkeypatch.setattr("agent.workspace_api.build_agent_flow_for_workspace", lambda _ws: flow)
    monkeypatch.setattr(
        "agent.workspace_api.bind_candidate_input",
        lambda _ws, _flow, target, source, candidate: calls.append(
            ("bind", target, source, candidate)
        ),
    )
    monkeypatch.setattr(
        "agent.workspace_api.materialize_candidate_config",
        lambda _ws, target, patch, candidate: calls.append(
            ("materialize", target, patch, candidate)
        ),
    )
    monkeypatch.setattr(
        "agent.workspace_api.validate_candidate_step_contract",
        lambda _ws, _target: "candidate-1",
    )
    monkeypatch.setattr(
        "agent.workspace_api.reapply_candidate_input_binding",
        lambda _ws, _flow, target: calls.append(("reapply", target)),
    )
    monkeypatch.setattr(
        "agent.workspace_api._init_db_engine_for_workspace_step",
        lambda _flow, step: calls.append(("init", step.name)),
    )

    result = api.candidate_rerun(
        CandidateRerunRequest(
            workspace_id="workspace-1",
            target_step="place",
            end_step="CTS",
            candidate_id="candidate-1",
            patch=[{"knob_id": "place.target_density", "value": 0.6}],
            execution_scope="full_flow",
            idempotency_key="episode-1.intervention-1",
        )
    )

    assert result["operationId"].startswith("operation-")
    assert result["kind"] == "candidate_rerun"
    assert result["origin"] == "agent"
    assert result["rerun"] is True
    assert result["step"] == "place"
    duplicate = api.candidate_rerun(
        CandidateRerunRequest(
            workspace_id="workspace-1",
            target_step="place",
            end_step="CTS",
            candidate_id="candidate-1",
            patch=[{"knob_id": "place.target_density", "value": 0.6}],
            execution_scope="full_flow",
            idempotency_key="episode-1.intervention-1",
        )
    )
    assert duplicate["operationId"] == result["operationId"]
    assert duplicate["deduplicated"] is True
    _wait_for_terminal(api.ecc_api.operations, result["operationId"])
    assert calls == [
        ("bind", "place", "Floorplan", "candidate-1"),
        (
            "materialize",
            "place",
            [{"knob_id": "place.target_density", "value": 0.6}],
            "candidate-1",
        ),
        ("reapply", "place"),
        ("init", "place"),
        ("init", "CTS"),
    ]
    assert flow.run_calls == [("place", True), ("CTS", True)]
    assert not list(place_output.iterdir())
    assert not list(place_analysis.iterdir())
    assert not list(cts_output.iterdir())


def test_candidate_rerun_rejects_multi_knob_patch_before_starting_an_operation(tmp_path):
    workspace = SimpleNamespace(directory=tmp_path)
    ecc_api = _EccApi(workspace)
    api = FlowAgentRuntimeApi(ecc_api)

    with pytest.raises(RuntimeApiError, match="exactly one patch item"):
        api.candidate_rerun(
            CandidateRerunRequest(
                workspace_id="workspace-1",
                target_step="place",
                end_step="CTS",
                candidate_id="candidate-1",
                patch=[
                    {"knob_id": "place.target_density", "value": 0.6},
                    {"knob_id": "place.routability_opt", "value": True},
                ],
                execution_scope="full_flow",
                idempotency_key="episode-1.intervention-1",
            )
        )

    assert ecc_api.operations.workspace_snapshot("workspace-1")["operations"] == []


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

    def _should_capture_session_db(self, _session):
        return False

    def _close_transient_flow_db(self, _flow):
        return None


class _Flow:
    def __init__(self, workspace, workspace_steps):
        self.workspace = workspace
        self.workspace_steps = workspace_steps
        self.run_calls = []

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
        return True

    def run_step(self, step, *, rerun, observer=None):
        self.run_calls.append((step.name, rerun))
        if observer is not None:
            observer.on_step_started(step)
            observer.on_step_completed(step, StateEnum.Success)
        return StateEnum.Success


def _wait_for_terminal(operations, operation_id):
    deadline = threading.Event()
    for _ in range(100):
        status = operations.operation_status(operation_id)
        if status["state"] in {"succeeded", "failed", "cancelled"}:
            assert status["state"] == "succeeded"
            return status
        deadline.wait(0.01)
    raise AssertionError("candidate operation did not reach a terminal state")
