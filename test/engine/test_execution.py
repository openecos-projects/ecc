from types import SimpleNamespace

from chipcompiler.data import StateEnum
from chipcompiler.engine.execution import ExecutionPlan, execute


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
    assert calls == [("flow", False, observer), ("Floorplan", True, observer)]


def test_execution_failure_keeps_main_blocking_semantics():
    class Flow:
        workspace = SimpleNamespace(flow=SimpleNamespace(data={"steps": []}))

        def run_steps(self, *, rerun=False, observer=None):
            return False

    result = execute(Flow(), ExecutionPlan(intent="run"), event_sink=object())

    assert not result.succeeded
    assert result.state == StateEnum.Imcomplete.value
