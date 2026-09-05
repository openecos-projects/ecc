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
):
    project_dir = create_cli_project()
    workspace_dir = os.path.join(project_dir, "baseline")
    project_path = Path(project_dir)
    manifest_stubs.write(project_path, [manifest_stubs.entry(project_path, "baseline")])
    create_flow_json(workspace_dir)

    rc = cli_main.run(["workspace", "refresh", "baseline", "--project", project_dir, "--json"])

    assert rc == 0
    records = json.loads(capsys.readouterr().out)["records"]
    assert records[-1]["status"] == "refreshed"
    assert flow_mocks.flow.instances[-1].create_called is True
    assert flow_mocks.flow.instances[-1].run_called is False
    document = json.loads((project_path / "project.json").read_text())
    assert document["workspaces"][0]["status"] == "not_started"
