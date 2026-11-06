from typing import Any

from chipcompiler.data import EccStep, StateEnum, Workspace
from chipcompiler.engine import flow as flow_module
from chipcompiler.engine.flow import EngineFlow
from chipcompiler.engine.step_execution import STEP_WORKER_MODULE, StepExecutionResult
from test.flow_fixture import step_fields


def test_engine_flow_passes_worker_module_and_layout_policy(monkeypatch, tmp_path):
    workspace: Any = Workspace(directory=tmp_path)
    workspace.flow.path = tmp_path / "flow.json"
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
    flow = EngineFlow(workspace)
    step = EccStep(name="route", directory=tmp_path, tool="ecc")
    flow.workspace_steps = [step]
    selected = {}

    def execute(_workspace, _step, _engine_db, **kwargs):
        selected.update(worker_module=kwargs["worker_module"], layout_image=kwargs["layout_image"])
        return StepExecutionResult(
            error=None, elapsed_seconds=0.0, peak_memory_mb=0.0, runtime="0:0:0"
        )

    monkeypatch.setattr(flow_module, "execute_tool_step", execute)
    monkeypatch.setattr(flow, "check_step_result", lambda **_kwargs: True)
    monkeypatch.setattr(flow, "_should_save_layout_image", lambda: False)

    def fail_parent_image(**_kwargs):
        raise AssertionError("parent image call")

    monkeypatch.setattr("chipcompiler.tools.save_layout_image", fail_parent_image)

    assert flow.run_step(step) is StateEnum.Success
    assert selected == {
        "worker_module": STEP_WORKER_MODULE,
        "layout_image": False,
    }
