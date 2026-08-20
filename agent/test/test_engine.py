from types import SimpleNamespace

import pytest

from agent.engine import AgentEngineFlow
from chipcompiler.data import EccStep, StateEnum, Workspace
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
    flow.engine_db = SimpleNamespace(engine=None, has_init=lambda: True)
    monkeypatch.setattr(flow, "check_step_result", lambda **_kwargs: True)

    def run_step(**_kwargs):
        if isinstance(tool_outcome, Exception):
            raise tool_outcome
        return tool_outcome

    monkeypatch.setattr("agent.engine.run_agent_step", run_step)

    assert flow.run_step(step) is expected_state
    assert flow.check_state("route", "ecc", expected_state)


def _marker_workspace(tmp_path):
    workspace = Workspace(directory=tmp_path, flow=Flow(path=tmp_path / "flow.json"))
    flow = AgentEngineFlow(workspace)
    workspace.flow.data = {"steps": [{"name": "route", "tool": "ecc", "state": "Unstart"}]}
    step = EccStep(name="route", directory=tmp_path, tool="ecc")
    flow.workspace_steps = [step]
    flow.engine_db = SimpleNamespace(engine=None, has_init=lambda: True)
    return flow, step


def test_agent_engine_emits_markers_around_step_writes(monkeypatch, tmp_path):
    """The agent executor frames the step stream with markers and never
    redirects stdio into a step log file."""
    flow, step = _marker_workspace(tmp_path)
    events = []
    monkeypatch.setattr(flow, "check_step_result", lambda **_kwargs: True)
    monkeypatch.setattr(
        "agent.engine.run_agent_step",
        lambda **kwargs: events.append(("tool", None)) or True,
    )
    monkeypatch.setattr(flow, "save_step_flow_facts", lambda **_kwargs: False)
    monkeypatch.setattr(
        "chipcompiler.tools.save_layout_image",
        lambda **_kwargs: events.append(("layout", None)),
    )
    monkeypatch.setattr(
        "chipcompiler.runtime.log_stream.emit_step_marker",
        lambda event, *, step, tool: events.append(("marker", event)),
    )

    assert flow.run_step(step) is StateEnum.Success
    end_index = events.index(("marker", "end"))
    assert events.index(("marker", "begin")) < events.index(("tool", None))
    assert events.index(("layout", None)) < end_index


def test_agent_engine_suppresses_end_marker_when_final_save_fails(monkeypatch, tmp_path):
    """A failed final save downgrades the record and suppresses the end
    marker, matching the base engine's authoritative-save contract."""
    flow, step = _marker_workspace(tmp_path)
    markers = []
    monkeypatch.setattr(flow, "check_step_result", lambda **_kwargs: True)
    monkeypatch.setattr("agent.engine.run_agent_step", lambda **kwargs: True)
    monkeypatch.setattr(
        "chipcompiler.runtime.log_stream.emit_step_marker",
        lambda event, *, step, tool: markers.append(event),
    )

    real_save = flow.save
    save_calls = []

    def save_failing_on_final():
        save_calls.append(len(save_calls) + 1)
        if len(save_calls) == 1:
            return real_save()  # the Ongoing save persists
        return False  # the one final save fails

    monkeypatch.setattr(flow, "save", save_failing_on_final)

    assert flow.run_step(step) is StateEnum.Imcomplete
    assert save_calls == [1, 2]
    assert markers == ["begin"]
    record = flow.get_step("route", "ecc")
    assert record["state"] == StateEnum.Imcomplete.value


def test_agent_engine_inherits_lifecycle_and_never_opens_step_logs(monkeypatch, tmp_path):
    """The inherited base lifecycle drives the agent tool hook end to end,
    and no step log file is opened even when the step declares a log path."""
    flow, step = _marker_workspace(tmp_path)
    declared_log = tmp_path / "route_ecc" / "log" / "route.log"
    step.log.file = declared_log
    tool_calls = []
    monkeypatch.setattr(flow, "check_step_result", lambda **_kwargs: True)
    monkeypatch.setattr(
        "agent.engine.run_agent_step",
        lambda **kwargs: tool_calls.append(kwargs) or True,
    )
    monkeypatch.setattr(flow, "save_step_flow_facts", lambda **_kwargs: False)
    monkeypatch.setattr("chipcompiler.tools.save_layout_image", lambda **_kwargs: True)
    markers = []
    monkeypatch.setattr(
        "chipcompiler.runtime.log_stream.emit_step_marker",
        lambda event, *, step, tool: markers.append(event),
    )

    assert flow.run_step(step) is StateEnum.Success
    # The agent runner hook was invoked through the base lifecycle.
    assert len(tool_calls) == 1
    assert tool_calls[0]["step"] is step
    assert markers == ["begin", "end"]
    assert not declared_log.exists()
    assert flow.check_state("route", "ecc", StateEnum.Success)
