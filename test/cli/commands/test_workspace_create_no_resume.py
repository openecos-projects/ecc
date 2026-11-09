"""Test that repeated workspace create does not resume flow execution (#393)."""

import json
import os
from pathlib import Path

from chipcompiler.cli import main as cli_main


def test_repeated_workspace_create_does_not_resume_flow(
    capsys, create_cli_project, manifest_stubs, plain_records, flow_mocks
):
    """Repeated workspace create should return success without running steps.

    Issue #393: workspace create on an existing workspace was calling
    run_existing_workspace, which resumed and executed the flow. With the fix,
    it should return immediately with status=refreshed without calling
    EngineFlow.run_steps.
    """
    project_dir = create_cli_project()
    project_path = Path(project_dir)
    workspace_dir = os.path.join(project_dir, "test-ws")

    # First create: should call engine to create workspace
    rc1 = cli_main.run(
        ["workspace", "create", "test-ws", "--project", project_dir, "--plain"]
    )
    assert rc1 == 0, capsys.readouterr().out
    records1 = plain_records(capsys.readouterr().out)
    assert records1[-1]["status"] == "refreshed"
    assert records1[-1]["workspace_id"] == "test-ws"

    # Register the workspace in manifest
    manifest_stubs.write(
        project_path, [manifest_stubs.entry(project_path, "test-ws")]
    )

    # Create a flow.json to simulate existing workspace with incomplete steps
    home = Path(workspace_dir) / "home"
    home.mkdir(parents=True, exist_ok=True)
    flow_json = home / "flow.json"
    flow_json.write_text(
        json.dumps(
            {
                "steps": [
                    {"name": "Synthesis", "tool": "yosys", "state": "Success"},
                    {"name": "Floorplan", "tool": "ecc", "state": "Pending"},
                ]
            }
        )
    )

    # Reset flow mock state
    flow_mocks.flow.instances = []

    # Second create: should NOT resume the flow, should return immediately
    rc2 = cli_main.run(
        ["workspace", "create", "test-ws", "--project", project_dir, "--plain"]
    )
    assert rc2 == 0, capsys.readouterr().out
    records2 = plain_records(capsys.readouterr().out)
    assert records2[-1]["status"] == "refreshed"
    assert records2[-1]["workspace_id"] == "test-ws"

    # Verify EngineFlow was NOT instantiated (no flow execution)
    assert len(flow_mocks.flow.instances) == 0, (
        "EngineFlow should not be created on second workspace create"
    )

    # Verify flow.json is unchanged (no steps were executed)
    flow_data = json.loads(flow_json.read_text())
    assert flow_data["steps"][1]["state"] == "Pending", "Flow should not have resumed"

