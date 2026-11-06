import json
from types import SimpleNamespace

import pytest

from agent.engine import AgentEngineFlow
from chipcompiler.data import ChecklistState, EccOutput, EccStep, StateEnum, Workspace
from chipcompiler.data.workspace import Flow
from chipcompiler.data.workspace.flow_types import FlowStepEntry
from chipcompiler.engine.flow_completion import sync_step_checklist
from chipcompiler.engine.step_execution import StepExecutionResult
from test.flow_fixture import step_directory, step_fields


@pytest.mark.parametrize(
    ("tool_outcome", "expected_state"),
    [
        (False, StateEnum.Imcomplete),
        (StateEnum.Invalid, StateEnum.Imcomplete),
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
    workspace.flow.data = {
        "schema_version": 2,
        "steps": [
            {
                "name": "route",
                "tool": "ecc",
                "state": "Unstart",
                **step_fields("route", "ecc"),
            }
        ],
    }
    step = EccStep(name="route", directory=tmp_path, tool="ecc")
    flow.workspace_steps = [step]
    vars(flow)["engine_db"] = SimpleNamespace(engine=None)
    monkeypatch.setattr(flow, "check_step_result", lambda **_kwargs: True)

    def run_step(**_kwargs):
        if isinstance(tool_outcome, Exception):
            raise tool_outcome
        return tool_outcome

    monkeypatch.setattr("agent.tools.run_step", run_step)

    assert flow.run_step(step) is expected_state
    assert flow.check_state("route", "ecc", expected_state)


def test_agent_engine_blocks_the_step_after_a_blocked_prerequisite(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    workspace = Workspace(directory=tmp_path, flow=Flow(path=home / "flow.json"))
    flow = AgentEngineFlow(workspace)
    workspace.flow.data = {
        "schema_version": 2,
        "steps": [
            {
                "name": "route",
                "tool": "ecc",
                "category": "PNR",
                "state": "Success",
                **step_directory("route", "ecc"),
            },
            {
                "name": "filler",
                "tool": "ecc",
                "category": "PNR",
                "state": "Unstart",
                **step_directory("filler", "ecc"),
            },
        ],
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
    monkeypatch.setattr("agent.tools.run_step", lambda **kwargs: calls.append(kwargs) or True)

    assert flow.run_step(EccStep(name="filler", tool="ecc")) is StateEnum.Invalid
    assert calls == []
    assert flow.get_step("filler", "ecc") == {
        "name": "filler",
        "tool": "ecc",
        "category": "PNR",
        "state": "Unstart",
        **step_directory("filler", "ecc"),
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
        "schema_version": 2,
        "steps": [
            {
                "name": "route",
                "tool": "ecc",
                "category": "PNR",
                "state": "Success",
                **step_directory("route", "ecc"),
            },
            {
                "name": "filler",
                "tool": "ecc",
                "category": "PNR",
                "state": "Unstart",
                **step_directory("filler", "ecc"),
            },
        ],
    }
    step = EccStep(name="filler", directory=tmp_path, tool="ecc")
    flow.workspace_steps = [step]
    vars(flow)["engine_db"] = SimpleNamespace(engine=None)
    if status is not None:
        route = flow.get_step("route", "ecc")
        assert route is not None
        route["checklist_status"] = {"status": status, "blocked": False}
        flow.save()
    called = []
    monkeypatch.setattr(
        "agent.tools.run_step", lambda **kwargs: called.append(kwargs["step"]) or True
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
            **step_fields(name, "ecc"),
        }
        for name, state in (("Synthesis", "Success"), ("Floorplan", "Incomplete"))
    ]
    workspace = Workspace(
        directory=tmp_path,
        flow=Flow(path=home / "flow.json"),
    )
    flow = AgentEngineFlow(workspace)
    workspace.flow.data = {"schema_version": 2, "steps": persisted_steps}
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
    vars(flow)["engine_db"] = SimpleNamespace(engine=None)
    monkeypatch.setattr("agent.tools.run_step", lambda **_kwargs: True)
    monkeypatch.setattr(flow, "check_step_result", lambda **_kwargs: True)

    assert flow.run_step(flow.workspace_steps[1], rerun=False) == StateEnum.Success
    persisted = json.loads((home / "flow.json").read_text())
    assert persisted["steps"][1]["state"] == StateEnum.Success.value


@pytest.mark.parametrize("candidate", [True, False])
def test_agent_engine_selects_worker_and_layout_policy_per_workspace(
    tmp_path, monkeypatch, candidate
):
    root = (
        tmp_path / ".agent" / "candidates" / "candidate-1" if candidate else tmp_path / "ordinary"
    )
    root.mkdir(parents=True)
    (root / "home").mkdir()
    workspace = Workspace(directory=root, flow=Flow(path=root / "home" / "flow.json"))
    flow = AgentEngineFlow(workspace)
    workspace.flow.data = {
        "schema_version": 2,
        "steps": [
            {
                "name": "route",
                "tool": "ecc",
                "state": "Unstart",
                **step_fields("route", "ecc"),
            }
        ],
    }
    step = EccStep(name="route", directory=root, tool="ecc")
    flow.workspace_steps = [step]
    selected = {}

    def execute(_workspace, _step, _engine_db, **kwargs):
        selected.update(worker_module=kwargs["worker_module"], layout_image=kwargs["layout_image"])
        return StepExecutionResult(
            error=None, elapsed_seconds=0.0, peak_memory_mb=0.0, runtime="0:0:0"
        )

    monkeypatch.setattr("chipcompiler.engine.flow.execute_tool_step", execute)
    monkeypatch.setattr(flow, "check_step_result", lambda **_kwargs: True)

    assert flow.run_step(step) is StateEnum.Success
    assert selected == {
        "worker_module": "agent.step_worker",
        "layout_image": not candidate,
    }


def test_agent_render_gate_runs_after_completion_without_rewriting_success(tmp_path, monkeypatch):
    workspace = Workspace(directory=tmp_path, flow=Flow(path=tmp_path / "flow.json"))
    flow = AgentEngineFlow(workspace)
    workspace.flow.data = {
        "schema_version": 2,
        "steps": [
            {
                "name": "route",
                "tool": "ecc",
                "state": "Unstart",
                **step_fields("route", "ecc"),
            }
        ],
    }
    step = EccStep(name="route", directory=tmp_path, tool="ecc")
    flow.workspace_steps = [step]
    vars(flow)["engine_db"] = SimpleNamespace(engine=None)
    monkeypatch.setattr("agent.tools.run_step", lambda **_kwargs: True)
    monkeypatch.setattr(flow, "check_step_result", lambda **_kwargs: True)
    calls = []
    observer = SimpleNamespace(
        on_step_completed=lambda *_args: calls.append("completed"),
        wait_for_step_rendered=lambda *_args: calls.append("render") or False,
    )

    assert flow.run_step(step, observer=observer) is StateEnum.Invalid
    assert calls == ["completed", "render"]
    assert flow.check_state("route", "ecc", StateEnum.Success)


def test_agent_render_gate_fails_open_on_observer_errors(tmp_path, monkeypatch):
    workspace = Workspace(directory=tmp_path, flow=Flow(path=tmp_path / "flow.json"))
    flow = AgentEngineFlow(workspace)
    workspace.flow.data = {
        "schema_version": 2,
        "steps": [
            {
                "name": "route",
                "tool": "ecc",
                "state": "Unstart",
                **step_fields("route", "ecc"),
            }
        ],
    }
    step = EccStep(name="route", directory=tmp_path, tool="ecc")
    flow.workspace_steps = [step]
    vars(flow)["engine_db"] = SimpleNamespace(engine=None)
    monkeypatch.setattr("agent.tools.run_step", lambda **_kwargs: True)
    monkeypatch.setattr(flow, "check_step_result", lambda **_kwargs: True)

    def fail_render(*_args):
        raise RuntimeError("render observer failed")

    observer = SimpleNamespace(wait_for_step_rendered=fail_render)

    assert flow.run_step(step, observer=observer) is StateEnum.Success


def test_agent_render_gate_is_not_called_for_failed_steps(tmp_path, monkeypatch):
    workspace = Workspace(directory=tmp_path, flow=Flow(path=tmp_path / "flow.json"))
    flow = AgentEngineFlow(workspace)
    workspace.flow.data = {
        "schema_version": 2,
        "steps": [
            {
                "name": "route",
                "tool": "ecc",
                "state": "Unstart",
                **step_fields("route", "ecc"),
            }
        ],
    }
    step = EccStep(name="route", directory=tmp_path, tool="ecc")
    flow.workspace_steps = [step]
    vars(flow)["engine_db"] = SimpleNamespace(engine=None)
    monkeypatch.setattr("agent.tools.run_step", lambda **_kwargs: False)
    calls = []
    observer = SimpleNamespace(wait_for_step_rendered=lambda *_args: calls.append("render"))

    assert flow.run_step(step, observer=observer) is StateEnum.Imcomplete
    assert calls == []


def test_agent_rerun_persists_ready_checklist_before_gating_successor(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    workspace = Workspace(directory=tmp_path, flow=Flow(path=home / "flow.json"))
    flow = AgentEngineFlow(workspace)
    workspace.flow.data = {
        "schema_version": 2,
        "steps": [
            {
                "name": "route",
                "tool": "ecc",
                "state": "Unstart",
                "checklist_status": {"status": "blocked", "blocked": True},
                **step_fields("route", "ecc"),
            },
            {
                "name": "filler",
                "tool": "ecc",
                "state": "Unstart",
                **step_fields("filler", "ecc"),
            },
        ],
    }
    flow.save()
    checklist = tmp_path / "route_checklist.json"
    route = EccStep(
        name="route",
        directory=tmp_path,
        tool="ecc",
        checklist=ChecklistState(path=checklist),
    )
    filler = EccStep(name="filler", directory=tmp_path, tool="ecc")
    flow.workspace_steps = [route, filler]
    vars(flow)["engine_db"] = SimpleNamespace(engine=None)
    monkeypatch.setattr(flow, "check_step_result", lambda **_kwargs: True)

    def run_step(*, step, **_kwargs):
        if step is route:
            checklist.write_text(
                json.dumps(
                    {
                        "status": "ready",
                        "checklist": [{"id": "route", "blocked": False}],
                    }
                ),
                encoding="utf-8",
            )
        return True

    monkeypatch.setattr("agent.tools.run_step", run_step)

    assert flow.run_step(route, rerun=True) is StateEnum.Success
    persisted = json.loads((home / "flow.json").read_text())
    assert persisted["steps"][0]["checklist_status"]["status"] == "passed"
    assert flow.run_step(filler, rerun=True) is StateEnum.Success
