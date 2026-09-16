from types import SimpleNamespace

import pytest

from chipcompiler.data import StateEnum
from chipcompiler.engine.execution import ExecutionPlan, event_sink_for_workspace, execute


def test_execution_plan_dispatches_full_flow_and_single_step():
    calls = []

    class Flow:
        def run_steps(self, *, rerun=False, observer=None):
            calls.append(("flow", rerun, observer))
            return True

        def get_workspace_step(self, step_id):
            return SimpleNamespace(name=step_id)

        def run_step(self, step, *, rerun=False, observer=None):
            calls.append((step.name, rerun, observer))
            return StateEnum.Success

    observer = object()
    flow = Flow()

    assert execute(flow, ExecutionPlan(intent="run"), event_sink=observer).succeeded
    step_result = execute(
        flow,
        ExecutionPlan(intent="rerun", step_id="Floorplan"),
        event_sink=observer,
    )

    assert step_result == step_result.__class__(
        succeeded=True,
        state=StateEnum.Success.value,
        step_id="Floorplan",
    )
    assert [call[:2] for call in calls] == [("flow", False), ("Floorplan", True)]
    assert all(call[2].delegate is observer for call in calls)


def test_execution_observer_does_not_hide_unknown_callbacks():
    from chipcompiler.engine.execution import ExecutionObserver

    with pytest.raises(AttributeError):
        _ = ExecutionObserver(object()).unknown_callback


def test_execution_plan_checks_cancel_before_each_selected_step():
    calls = []

    class Cancelled(RuntimeError):
        pass

    class Observer:
        fatal_observer = True

        def __init__(self):
            self.completed = 0

        def on_step_completed(self, _step, _state, _error=None):
            self.completed += 1

        def raise_if_cancelled(self):
            if self.completed:
                raise Cancelled

    class Flow:
        def get_workspace_step(self, step_id):
            return SimpleNamespace(name=step_id)

        def run_step(self, step, *, rerun=False, observer=None):
            calls.append(step.name)
            observer.on_step_completed(step, StateEnum.Success)
            return StateEnum.Success

    with pytest.raises(Cancelled):
        execute(
            Flow(),
            ExecutionPlan(intent="run", step_ids=("Synthesis", "Floorplan")),
            event_sink=Observer(),
        )

    assert calls == ["Synthesis"]


def test_execution_failure_keeps_main_blocking_semantics():
    class Flow:
        workspace = SimpleNamespace(flow=SimpleNamespace(data={"steps": []}))

        def run_steps(self, *, rerun=False, observer=None):
            return False

    result = execute(Flow(), ExecutionPlan(intent="run"), event_sink=object())

    assert not result.succeeded
    assert result.state == StateEnum.Imcomplete.value


def test_default_execution_observer_commits_completed_steps(monkeypatch, tmp_path):
    from chipcompiler.engine import execution

    committed = []

    class Flow:
        workspace = SimpleNamespace(directory=tmp_path)

        def run_steps(self, *, rerun=False, observer=None):
            observer.on_step_completed(SimpleNamespace(name="synthesis"), StateEnum.Success)
            return True

    monkeypatch.setattr(
        execution,
        "_EngineeringCommitSink",
        lambda workspace: SimpleNamespace(
            snapshot={"workspaceId": "workspace-1", "workspaceRevision": 1},
            on_step_completed=lambda step, state, error=None: committed.append((step.name, state)),
        ),
    )

    result = execution.execute(Flow(), execution.ExecutionPlan(intent="run"))

    assert result.succeeded
    assert committed == [("synthesis", StateEnum.Success)]


def test_execution_reports_ordered_steps_and_completed_default_is_noop():
    calls = []

    class Flow:
        workspace = SimpleNamespace(
            flow=SimpleNamespace(data={"steps": [{"name": "synthesis", "state": "Success"}]})
        )

        def run_steps(self, **_kwargs):
            calls.append("run")
            return True

    result = execute(Flow(), ExecutionPlan(intent="run"))

    assert result.succeeded
    assert result.no_op
    assert result.executed_steps == ()
    assert result.failed_step is None
    assert calls == []


def test_event_sink_for_workspace_is_none_without_directory():
    assert event_sink_for_workspace(SimpleNamespace()) is None
    assert event_sink_for_workspace(SimpleNamespace(directory=None)) is None
