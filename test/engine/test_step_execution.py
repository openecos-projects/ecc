import json
from types import SimpleNamespace
from typing import Any

import pytest

from chipcompiler import tools
from chipcompiler.data import EccFeature, EccStep, StateEnum, Workspace
from chipcompiler.engine.flow import runner as flow_module
from chipcompiler.engine.flow.runner import EngineFlow
from chipcompiler.engine.step.execution import STEP_WORKER_MODULE, StepExecutionResult
from test.flow_fixture import step_fields


def test_engine_flow_passes_worker_module_and_layout_policy(monkeypatch, tmp_path):
    workspace: Any = Workspace(directory=tmp_path)
    workspace.flow.path = tmp_path / "flow.json"
    workspace.flow.data = {
        "schema_version": 3,
        "steps": [
            {
                "name": "routing",
                "tool": "ecc",
                "state": "Unstart",
                **step_fields("routing", "ecc"),
            }
        ],
    }
    flow = EngineFlow(workspace)
    step = EccStep(name="routing", directory=tmp_path, tool="ecc")
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


def test_run_steps_never_initializes_native_db_or_redirects_in_parent(monkeypatch, tmp_path):
    from chipcompiler.engine import EngineDB
    from chipcompiler.engine.step import execution as step_execution
    from chipcompiler.engine.step.execution import StepExecutionResult
    from chipcompiler.tools.ecc.module import ECCToolsModule

    workspace: Any = Workspace(directory=tmp_path)
    workspace.flow.path = tmp_path / "flow.json"
    workspace.flow.data = {
        "schema_version": 3,
        "steps": [
            {
                "name": "routing",
                "tool": "ecc",
                "state": "Unstart",
                **step_fields("routing", "ecc"),
            }
        ],
    }
    engine_flow: Any = EngineFlow(workspace)
    engine_flow.workspace_steps = [EccStep(name="routing", directory=tmp_path, tool="ecc")]
    redirects = []
    monkeypatch.setattr(
        "chipcompiler.utility.log.redirect_stdio_to_file", lambda path: redirects.append(path)
    )

    def fail_native_init(*_args, **_kwargs):
        raise AssertionError("parent native DB initialization must not run")

    monkeypatch.setattr(EngineDB, "create_db_engine", fail_native_init)
    monkeypatch.setattr(ECCToolsModule, "__init__", fail_native_init)
    monkeypatch.setattr(
        step_execution,
        "_execute_in_worker",
        lambda *_args, **_kwargs: StepExecutionResult(
            error=None, elapsed_seconds=0.0, peak_memory_mb=0.0, runtime="0:0:0"
        ),
    )
    monkeypatch.setattr(engine_flow, "check_step_result", lambda **_kwargs: True)
    monkeypatch.setattr(tools, "save_layout_image", lambda **_kwargs: True)
    monkeypatch.setattr(flow_module, "log_flow", lambda **_kwargs: None)

    assert engine_flow.run_steps() is True
    assert redirects == []


def test_engine_flow_worker_failure_marks_incomplete_not_success(
    monkeypatch,
    tmp_path,
):
    """A worker-side failure reaches a terminal Incomplete ledger state."""
    workspace: Any = Workspace(directory=tmp_path)
    flow_path = tmp_path / "home" / "flow.json"
    flow_path.parent.mkdir(parents=True)
    flow_path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "steps": [
                    {
                        "name": "routing",
                        "tool": "ecc",
                        "state": "Unstart",
                        "runtime": "",
                        "peak memory (mb)": 0,
                        "info": {},
                        **step_fields("routing", "ecc"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    workspace.flow.path = flow_path
    workspace.flow.data = {
        "schema_version": 3,
        "steps": [
            {
                "name": "routing",
                "tool": "ecc",
                "state": "Unstart",
                **step_fields("routing", "ecc"),
            }
        ],
    }
    workspace_step = EccStep(
        name="routing",
        directory=tmp_path,
        tool="ecc",
        feature=EccFeature(step=tmp_path / "feature" / "routing.step.json"),
    )
    step_feature_path = workspace_step.feature.step
    assert step_feature_path is not None
    step_feature_path.parent.mkdir(parents=True, exist_ok=True)
    step_feature_path.write_text("{}", encoding="utf-8")
    engine_flow: Any = EngineFlow(workspace)
    engine_flow.workspace_steps = [workspace_step]
    engine_flow.engine_db = SimpleNamespace(engine=None)

    from chipcompiler.engine.step import execution as step_execution
    from chipcompiler.engine.step.execution import StepExecutionResult

    monkeypatch.setattr(
        step_execution,
        "_execute_in_worker",
        lambda *_args, **_kwargs: StepExecutionResult(
            error="layout render exploded",
            elapsed_seconds=0.0,
            peak_memory_mb=0.0,
            runtime="0:0:0",
        ),
    )
    monkeypatch.setattr(
        tools,
        "save_layout_image",
        lambda **_kwargs: pytest.fail("parent must not render a layout image"),
    )

    result = engine_flow.run_step(workspace_step)

    assert result == StateEnum.Imcomplete
    persisted = json.loads(flow_path.read_text(encoding="utf-8"))
    assert persisted["steps"][0]["state"] == StateEnum.Imcomplete.value
