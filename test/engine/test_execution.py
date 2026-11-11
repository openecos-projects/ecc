from types import SimpleNamespace
from typing import Any

import pytest

from chipcompiler.data import StateEnum
from chipcompiler.engine.execution import ExecutionPlan, ExecutionResult, execute
from chipcompiler.engine.observers import event_sink_for_workspace


def test_execution_plan_dispatches_full_flow_and_selected_steps():
    calls = []

    class Flow:
        def run_steps(self, *, rerun=False, observer: Any = None, steps=None):
            calls.append(
                (None if steps is None else [step.name for step in steps], rerun, observer)
            )
            return True

        def get_workspace_step(self, step_id):
            return SimpleNamespace(name=step_id)

    observer = object()
    flow = Flow()

    assert execute(flow, ExecutionPlan(intent="run"), event_sink=observer).succeeded
    step_result = execute(
        flow,
        ExecutionPlan(intent="rerun", step_ids=("Floorplan", "place")),
        event_sink=observer,
    )

    assert step_result == step_result.__class__(
        succeeded=True,
        state=StateEnum.Success.value,
    )
    assert [call[:2] for call in calls] == [(None, False), (["Floorplan", "place"], True)]
    assert all(call[2].delegate is observer for call in calls)


def test_execution_of_a_single_step_reports_its_id():
    class Flow:
        def run_steps(self, *, rerun=False, observer: Any = None, steps=None):
            return True

        def get_workspace_step(self, step_id):
            return SimpleNamespace(name=step_id)

    result = execute(
        Flow(), ExecutionPlan(intent="rerun", step_id="Floorplan"), event_sink=object()
    )

    assert result == ExecutionResult(
        succeeded=True, state=StateEnum.Success.value, step_id="Floorplan"
    )


def test_execution_observer_does_not_hide_unknown_callbacks():
    from chipcompiler.engine.observers import ExecutionObserver

    callback = "unknown_callback"
    with pytest.raises(AttributeError):
        _ = getattr(ExecutionObserver(object()), callback)


def test_execution_reports_an_interruption_and_reraises():
    events = []

    class Cancelled(RuntimeError):
        pass

    class Sink:
        def on_execution_started(self, intent, step_ids):
            events.append(("started", intent, step_ids))

        def on_execution_finished(self, state, error):
            events.append(("finished", state, error))

    class Flow:
        def get_workspace_step(self, step_id):
            return SimpleNamespace(name=step_id)

        def run_steps(self, *, rerun=False, observer: Any = None, steps=None):
            raise Cancelled("run cancelled at a step boundary")

    with pytest.raises(Cancelled):
        execute(
            Flow(),
            ExecutionPlan(intent="rerun", step_ids=("Synthesis", "Floorplan")),
            event_sink=Sink(),
        )

    assert events == [
        ("started", "rerun", ("Synthesis", "Floorplan")),
        ("finished", "interrupted", "run cancelled at a step boundary"),
    ]


def test_execution_of_an_unknown_step_runs_nothing_and_is_reported():
    events = []

    class Sink:
        def on_execution_finished(self, state, error):
            events.append((state, error))

    class Flow:
        def get_workspace_step(self, step_id):
            return None if step_id == "nope" else SimpleNamespace(name=step_id)

        def run_steps(self, **_kwargs):
            pytest.fail("no step may run when the selection is unknown")

    with pytest.raises(ValueError, match="step not found: nope"):
        execute(
            Flow(),
            ExecutionPlan(intent="rerun", step_ids=("Synthesis", "nope")),
            event_sink=Sink(),
        )

    assert events == [("interrupted", "step not found: nope")]


@pytest.mark.parametrize("selected", [True, False], ids=["selection", "full flow"])
def test_execution_reports_wave_steps_in_flow_order(selected):
    names = ("lvs", "drc", "antennaCheck", "RCX")

    class Flow:
        workspace_steps = [SimpleNamespace(name=name) for name in names]
        workspace = SimpleNamespace(flow=SimpleNamespace(data={"schema_version": 2, "steps": []}))

        def get_workspace_step(self, step_id):
            return SimpleNamespace(name=step_id)

        def run_steps(self, *, rerun=False, observer: Any = None, steps=None):
            # Steps of a parallel wave complete in any order.
            for name, state in [
                ("RCX", StateEnum.Imcomplete),
                ("antennaCheck", StateEnum.Success),
                ("drc", StateEnum.Invalid),
                ("lvs", StateEnum.Success),
            ]:
                observer.on_step_completed(SimpleNamespace(name=name), state)
            return False

    plan = ExecutionPlan(intent="rerun", step_ids=names if selected else ())
    result = execute(Flow(), plan, event_sink=object())

    assert result == ExecutionResult(
        succeeded=False,
        state=StateEnum.Imcomplete.value,
        executed_steps=("lvs", "antennaCheck"),
        failed_step="drc",
    )


def test_execution_failure_keeps_main_blocking_semantics():
    class Flow:
        workspace = SimpleNamespace(flow=SimpleNamespace(data={"schema_version": 2, "steps": []}))

        def run_steps(self, *, rerun=False, observer: Any = None):
            return False

    result = execute(Flow(), ExecutionPlan(intent="run"), event_sink=object())

    assert not result.succeeded
    assert result.state == StateEnum.Imcomplete.value


def test_successful_flow_with_advisory_failure_has_no_blocking_failed_step():
    class Flow:
        def run_steps(self, *, rerun=False, observer: Any = None):
            observer.on_step_completed(SimpleNamespace(name="emir"), StateEnum.Imcomplete)
            observer.on_step_completed(SimpleNamespace(name="Harden"), StateEnum.Success)
            return True

    result = execute(Flow(), ExecutionPlan(intent="run"), event_sink=object())
    assert result.succeeded
    assert result.failed_step is None
    assert result.executed_steps == ("Harden",)


def test_default_execution_observer_commits_completed_steps(monkeypatch, tmp_path):
    from chipcompiler.engine import execution, observers

    committed = []

    class Flow:
        workspace = SimpleNamespace(directory=tmp_path)

        def run_steps(self, *, rerun=False, observer: Any = None):
            observer.on_step_completed(SimpleNamespace(name="synthesis"), StateEnum.Success)
            return True

    monkeypatch.setattr(
        observers,
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
            flow=SimpleNamespace(
                data={"schema_version": 2, "steps": [{"name": "synthesis", "state": "Success"}]}
            )
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
