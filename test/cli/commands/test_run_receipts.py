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


def test_finished_resume_records_success_and_consumes_run_id(fresh_project, capsys):
    project = ["--project", str(fresh_project), "--plain"]
    assert (
        cli_main.run(
            [
                "workspace",
                "create",
                "finished",
                "--from",
                "synthesis",
                "--to",
                "synthesis",
                *project,
            ]
        )
        == 0
    )
    workspace = fresh_project / "finished"
    ledger = workspace / "home/flow.json"
    flow = json.loads(ledger.read_text())
    flow["steps"][0]["state"] = "Success"
    ledger.write_text(json.dumps(flow))
    run_id = str(uuid.uuid4())
    resume = ["run", "--workspace", "finished", "--resume", "--run-id", run_id, *project]
    capsys.readouterr()
    assert cli_main.run(resume) == 0
    assert "no_op=True" in capsys.readouterr().out
    receipt = workspace / "log" / f"{run_id}.run.json"
    original = receipt.read_bytes()
    assert json.loads(original)["state"] == "succeeded"
    assert cli_main.run(resume) == 1
    assert "run_id_already_used" in capsys.readouterr().out
    assert receipt.read_bytes() == original
