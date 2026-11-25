import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.cli import main as cli_main


@pytest.mark.parametrize(
    ("completed_steps", "failed_step"),
    [
        pytest.param(("antenna_check", "rcx"), "rcx", id="advisory-finishes-first"),
        pytest.param(("rcx", "drc"), "drc", id="blocking-failures-follow-flow-order"),
        pytest.param(("antenna_check",), None, id="advisory-only"),
    ],
)
def test_run_receipt_uses_the_blocking_step_error(
    create_cli_project, flow_mocks, monkeypatch, completed_steps, failed_step
):
    from chipcompiler.data import StateEnum
    from chipcompiler.engine import execution
    from chipcompiler.engine.snapshot import store

    project = create_cli_project()
    workdir = Path(project) / "default"
    snapshot_data = {"workspaceId": "default"}
    monkeypatch.setattr(store, "ensure_engineering_snapshot", lambda *_: snapshot_data)
    monkeypatch.setattr(store, "commit_engineering_snapshot", lambda *_, **__: snapshot_data)
    execute = execution.execute

    def execute_stub_flow(flow, plan, **kwargs):
        flow.workspace.directory = workdir
        flow.workspace.flow.path = None
        return execute(flow, plan, **kwargs)

    def complete_steps(flow, *, observer, **_kwargs):
        steps = {name: SimpleNamespace(name=name) for name in ("drc", "antenna_check", "rcx")}
        flow.workspace_steps = list(steps.values())
        for name in completed_steps:
            observer.on_step_completed(steps[name], StateEnum.Imcomplete, f"{name} tool failed")
        return failed_step is None

    monkeypatch.setattr("chipcompiler.engine.execute", execute_stub_flow)
    monkeypatch.setattr(flow_mocks.flow, "run_steps", complete_steps)
    run_id = str(uuid.uuid4())

    exit_code = cli_main.run(["run", "--project", project, "--run-id", run_id, "--plain"])

    receipt = json.loads((workdir / "log" / f"{run_id}.run.json").read_text())
    if failed_step is None:
        assert (exit_code, receipt["state"], receipt.get("error")) == (0, "succeeded", None)
    else:
        assert (exit_code, receipt["state"], receipt["error"]) == (
            1,
            "failed",
            {
                "code": "step_worker_failed",
                "message": f"{failed_step}: {failed_step} tool failed",
            },
        )
