import json
from types import SimpleNamespace

import pytest

from agent.engine import AgentEngineFlow
from chipcompiler.data import ChecklistState, EccOutput, EccStep, StateEnum, Workspace
from chipcompiler.data.workspace import Flow
from chipcompiler.data.workspace.flow_types import FlowStepEntry
from chipcompiler.engine.flow_completion import sync_step_checklist, write_step_checklist


@pytest.mark.parametrize(
    ("tool_outcome", "expected_state"),
    [
        (False, StateEnum.Imcomplete),
        (StateEnum.Invalid, StateEnum.Invalid),
        (RuntimeError("native tool failed"), StateEnum.Imcomplete),
    ],
)
def test_agent_engine_requires_successful_tool_result(
    monkeypatch,
    tmp_path,
    tool_outcome,
    expected_state,
):
    workspace = Workspace(directory=tmp_path, flow=Flow(path=tmp_path / "flow.json"))
    flow = AgentEngineFlow(workspace)
    workspace.flow.data = {"steps": [{"name": "route", "tool": "ecc", "state": "Unstart"}]}
    step = EccStep(name="route", directory=tmp_path, tool="ecc")
    flow.workspace_steps = [step]
    flow.engine_db = SimpleNamespace(engine=None)
    monkeypatch.setattr(flow, "check_step_result", lambda **_kwargs: True)

    def run_step(**_kwargs):
        if isinstance(tool_outcome, Exception):
            raise tool_outcome
        return tool_outcome

    monkeypatch.setattr("agent.engine.run_agent_step", run_step)

    assert flow.run_step(step) is expected_state
    assert flow.check_state("route", "ecc", expected_state)


def test_agent_engine_blocks_the_step_after_a_blocked_prerequisite(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    workspace = Workspace(directory=tmp_path, flow=Flow(path=home / "flow.json"))
    flow = AgentEngineFlow(workspace)
    workspace.flow.data = {
        "steps": [
            {"name": "route", "tool": "ecc", "category": "PNR", "state": "Success"},
            {"name": "filler", "tool": "ecc", "category": "PNR", "state": "Unstart"},
        ]
    }
    checklist_path = tmp_path / "route_checklist.json"
    checklist_path.write_text(
        json.dumps({"status": "blocked", "checklist": [{"id": "route", "blocked": True}]}),
        encoding="utf-8",
    )
    sync_step_checklist(
        flow,
        EccStep(
            name="route",
            tool="ecc",
            directory=tmp_path,
            checklist=ChecklistState(path=checklist_path),
        ),
    )
    calls = []
    monkeypatch.setattr(
        "agent.engine.run_agent_step", lambda **kwargs: calls.append(kwargs) or True
    )

    assert flow.run_step(EccStep(name="filler", tool="ecc")) is StateEnum.Invalid
    assert calls == []
    assert flow.get_step("filler", "ecc") == {
        "name": "filler",
        "tool": "ecc",
        "category": "PNR",
        "state": "Unstart",
        "checklist": [],
        "checklist_status": {
            "status": "blocked",
            "blocked": True,
            "failed_items": ["prerequisite:route"],
            "source": "home/flow.json",
        },
    }
    assert all(not isinstance(step.get("checklist"), dict) for step in workspace.flow.data["steps"])


@pytest.mark.parametrize("status", ["passed", "attention", "unknown", None])
def test_agent_engine_runs_the_step_after_a_non_blocked_prerequisite(tmp_path, monkeypatch, status):
    home = tmp_path / "home"
    home.mkdir()
    workspace = Workspace(directory=tmp_path, flow=Flow(path=home / "flow.json"))
    flow = AgentEngineFlow(workspace)
    workspace.flow.data = {
        "steps": [
            {"name": "route", "tool": "ecc", "category": "PNR", "state": "Success"},
            {"name": "filler", "tool": "ecc", "category": "PNR", "state": "Unstart"},
        ]
    }
    step = EccStep(name="filler", directory=tmp_path, tool="ecc")
    flow.workspace_steps = [step]
    flow.engine_db = SimpleNamespace(engine=None)
    if status is not None:
        write_step_checklist(
            flow,
            flow.get_step("route", "ecc"),
            items=[],
            status={"status": status, "blocked": False},
        )
    called = []
    monkeypatch.setattr(
        "agent.engine.run_agent_step", lambda **kwargs: called.append(kwargs["step"]) or True
    )
    monkeypatch.setattr(flow, "check_step_result", lambda **_kwargs: True)

    assert flow.run_step(step) is StateEnum.Success
    assert called == [step]


def test_agent_incomplete_step_normalized_on_resume(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    persisted_steps: list[FlowStepEntry] = [
        {
            "name": name,
            "tool": "ecc",
            "state": state,
            "runtime": "",
            "peak memory (mb)": 0,
            "info": {},
        }
        for name, state in (("Synthesis", "Success"), ("Floorplan", "Incomplete"))
    ]
    workspace = Workspace(
        directory=tmp_path,
        flow=Flow(path=home / "flow.json"),
    )
    flow = AgentEngineFlow(workspace)
    workspace.flow.data = {"steps": persisted_steps}
    flow.save()
    flow.workspace_steps = []
    for name in ("Synthesis", "Floorplan"):
        directory = tmp_path / f"{name}_ecc"
        directory.mkdir()
        flow.workspace_steps.append(
            EccStep(
                name=name,
                tool="ecc",
                directory=directory,
                output=EccOutput(verilog=directory / "design.v"),
            )
        )
    flow.engine_db = SimpleNamespace(engine=None)
    monkeypatch.setattr("agent.engine.run_agent_step", lambda **_kwargs: True)
    monkeypatch.setattr(flow, "check_step_result", lambda **_kwargs: True)

    assert flow.run_step(flow.workspace_steps[1], rerun=False) == StateEnum.Success
    persisted = json.loads((home / "flow.json").read_text())
    assert persisted["steps"][1]["state"] == StateEnum.Success.value


def test_agent_engine_skips_layout_snapshot_for_candidate_workspace(tmp_path, monkeypatch):
    root = tmp_path / ".agent" / "candidates" / "candidate-1"
    root.mkdir(parents=True)
    workspace = Workspace(directory=root, flow=Flow(path=root / "home" / "flow.json"))
    flow = AgentEngineFlow(workspace)
    step = EccStep(name="place", directory=root / "place_dreamplace", tool="ecc")
    calls = []
    monkeypatch.setattr(flow, "save_step_flow_facts", lambda **_kwargs: True)
    monkeypatch.setattr(
        "chipcompiler.tools.build_step_metrics",
        lambda **_kwargs: calls.append("metrics"),
    )
    monkeypatch.setattr(
        "chipcompiler.tools.save_layout_image",
        lambda **_kwargs: calls.append("snapshot"),
    )

    flow._save_agent_step_facts(step, StateEnum.Success, 1.0, 2.0, {})

    assert calls == ["metrics"]
