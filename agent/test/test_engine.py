import json
from types import SimpleNamespace

import pytest

from agent.engine import AgentEngineFlow
from chipcompiler.data import EccOutput, EccStep, StateEnum, Workspace
from chipcompiler.data.workspace import Flow


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


def test_agent_incomplete_step_normalized_on_resume(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    persisted_steps = [
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
