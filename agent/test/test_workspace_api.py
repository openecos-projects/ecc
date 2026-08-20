import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.requests import CandidateRerunRequest
from agent.workspace_api import FlowAgentRuntimeApi, _candidate_step_artifact_dirs
from chipcompiler.data import StateEnum
from chipcompiler.data.workspace.layout import EccOutput


def test_candidate_artifact_dirs_support_typed_step_outputs(tmp_path):
    output_dir = tmp_path / "place_dreamplace" / "output"
    analysis_dir = tmp_path / "place_dreamplace" / "analysis"
    step = SimpleNamespace(
        output=EccOutput(dir=output_dir),
        analysis={"dir": analysis_dir},
    )

    assert _candidate_step_artifact_dirs(step) == (Path(output_dir), Path(analysis_dir))


def test_candidate_rerun_uses_the_agent_flow_and_replays_its_receipts(monkeypatch, tmp_path):
    workspace = SimpleNamespace(
        directory=tmp_path,
        flow=SimpleNamespace(
            data={
                "steps": [
                    {"name": "fixFanout", "tool": "ecc", "state": "Success"},
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
            SimpleNamespace(name="fixFanout", tool="ecc", output={}),
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

    result = api.candidate_rerun(
        CandidateRerunRequest(
            workspace_id="workspace-1",
            target_step="place",
            end_step="CTS",
            candidate_id="candidate-1",
            patch=[{"knob_id": "place.target_density", "value": 0.6}],
            execution_scope="full_flow",
        )
    )

    assert result == {
        "target_step": "place",
        "end_step": "CTS",
        "execution_scope": "full_flow",
    }
    assert calls == [
        ("bind", "place", "fixFanout", "candidate-1"),
        (
            "materialize",
            "place",
            [{"knob_id": "place.target_density", "value": 0.6}],
            "candidate-1",
        ),
        ("reapply", "place"),
    ]
    assert flow.run_calls == [("place", True), ("CTS", True)]
    assert not list(place_output.iterdir())
    assert not list(place_analysis.iterdir())
    assert not list(cts_output.iterdir())


def test_candidate_step_exception_reconciles_the_record(monkeypatch, tmp_path, capfd):
    """A run_step raising after its begin marker must downgrade the record
    before the exception propagates — not leave Success over a partial log."""
    (tmp_path / "home").mkdir()
    steps = [{"name": "place", "tool": "dreamplace", "state": "Success"}]
    (tmp_path / "home" / "flow.json").write_text(json.dumps({"steps": steps}))
    workspace = SimpleNamespace(
        directory=tmp_path,
        flow=SimpleNamespace(data={"steps": [dict(s) for s in steps]}),
    )
    place_output = tmp_path / "place_dreamplace" / "output"
    place_output.mkdir(parents=True)
    step = SimpleNamespace(
        name="place",
        tool="dreamplace",
        output=EccOutput(dir=place_output),
        analysis={},
    )
    flow = _Flow(workspace, (step,))

    from chipcompiler.runtime.log_stream import emit_step_marker

    def raising_run_step(step, *, rerun):
        flow.run_calls.append((step.name, rerun))
        emit_step_marker("begin", step=step.name, tool=step.tool)
        os.write(2, b"partial\n")
        raise RuntimeError("layout save blew up")

    flow.run_step = raising_run_step
    flow.set_state = lambda name, tool, state: (
        workspace.flow.data["steps"][0].update({"state": state.value})
    )

    api = FlowAgentRuntimeApi(_EccApi(workspace))
    monkeypatch.setattr("agent.workspace_api.build_agent_flow_for_workspace", lambda _ws: flow)

    with pytest.raises(RuntimeError, match="layout save blew up"):
        api.candidate_rerun(
            CandidateRerunRequest(
                workspace_id="workspace-1",
                target_step="place",
                end_step="place",
                candidate_id=None,
                patch=None,
                execution_scope="single_step",
            )
        )

    assert workspace.flow.data["steps"][0]["state"] == StateEnum.Imcomplete.value
    assert "ECC-STEP" not in capfd.readouterr().err


class _EccApi:
    def __init__(self, workspace):
        self.session = SimpleNamespace(workspace=workspace, db_handle=None)

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

    def run_step(self, step, *, rerun):
        self.run_calls.append((step.name, rerun))
        return StateEnum.Success
