import json
import os
from pathlib import Path

from chipcompiler.cli import main as cli_main


def test_workspace_refresh_recreates_without_running(
    capsys,
    create_cli_project,
    create_flow_json,
    flow_mocks,
    manifest_stubs,
    plain_records,
):
    project_dir = create_cli_project()
    workspace_dir = os.path.join(project_dir, "baseline")
    project_path = Path(project_dir)
    manifest_stubs.write(project_path, [manifest_stubs.entry(project_path, "baseline")])
    create_flow_json(workspace_dir)

    rc = cli_main.run(["workspace", "refresh", "baseline", "--project", project_dir, "--plain"])

    assert rc == 0
    records = plain_records(capsys.readouterr().out)
    assert records[-1]["status"] == "refreshed"
    assert flow_mocks.flow.instances[-1].create_called is True
    assert flow_mocks.flow.instances[-1].run_called is False
    document = json.loads((project_path / "project.json").read_text())
    assert document["workspaces"][0]["status"] == "not_started"


def test_refresh_failure_restores_the_previous_workspace(
    capsys,
    create_cli_project,
    create_flow_json,
    flow_mocks,
    manifest_stubs,
    monkeypatch,
    plain_records,
):
    project_dir = create_cli_project()
    workspace_dir = os.path.join(project_dir, "baseline")
    project_path = Path(project_dir)
    manifest_stubs.write(
        project_path,
        [manifest_stubs.entry(project_path, "baseline", status="success")],
    )
    create_flow_json(workspace_dir)
    sentinel = Path(workspace_dir, "Synthesis_yosys", "output", "gcd.v.gz")
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("previous artifacts")

    def failing_create(**_kwargs):
        raise RuntimeError("config generation exploded")

    monkeypatch.setattr("chipcompiler.data.create_workspace", failing_create)

    rc = cli_main.run(["workspace", "refresh", "baseline", "--project", project_dir, "--plain"])

    assert rc == 1
    # The previous workspace is back at its path with its artifacts, and no
    # rename-aside backup directory lingers behind.
    assert sentinel.read_text() == "previous artifacts"
    assert [name for name in os.listdir(project_dir) if "overwritten" in name] == []
    # The restored workspace keeps its prior manifest status.
    document = json.loads((project_path / "project.json").read_text())
    assert document["workspaces"][0]["status"] == "success"
