"""Test that repeated workspace create does not resume flow execution (#393)."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

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
    rc1 = cli_main.run(["workspace", "create", "test-ws", "--project", project_dir, "--plain"])
    assert rc1 == 0, capsys.readouterr().out
    records1 = plain_records(capsys.readouterr().out)
    assert records1[-1]["status"] == "refreshed"
    assert records1[-1]["workspace_id"] == "test-ws"

    # Register the workspace in manifest
    manifest_stubs.write(project_path, [manifest_stubs.entry(project_path, "test-ws")])

    # Create a flow.json to simulate existing workspace with incomplete steps
    home = Path(workspace_dir) / "home"
    home.mkdir(parents=True, exist_ok=True)
    flow_json = home / "flow.json"
    flow_json.write_text(
        json.dumps(
            {
                "steps": [
                    {"name": "synthesis", "tool": "yosys", "state": "Success"},
                    {"name": "floorplan", "tool": "ecc", "state": "Pending"},
                ]
            }
        )
    )

    # Reset flow mock state
    flow_mocks.flow.instances = []

    # Second create: should NOT resume the flow, should return immediately
    rc2 = cli_main.run(["workspace", "create", "test-ws", "--project", project_dir, "--plain"])
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


def _existing_workspace(capsys, create_cli_project, manifest_stubs, flow_mocks):
    """A registered workspace whose ledger has one finished and one pending step."""
    project_dir = create_cli_project()
    project_path = Path(project_dir)
    assert (
        cli_main.run(["workspace", "create", "test-ws", "--project", project_dir, "--plain"]) == 0
    )
    capsys.readouterr()
    manifest_stubs.write(project_path, [manifest_stubs.entry(project_path, "test-ws")])
    home = project_path / "test-ws" / "home"
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
    flow_mocks.flow.instances = []
    return project_dir, flow_json


def test_workspace_create_with_a_range_does_not_run_an_existing_workspace(
    capsys, create_cli_project, manifest_stubs, plain_records, flow_mocks
):
    """Issue #442: --from/--to sent an existing workspace down the run selector path."""
    project_dir, flow_json = _existing_workspace(
        capsys, create_cli_project, manifest_stubs, flow_mocks
    )
    before = flow_json.read_text()

    rc = cli_main.run(
        ["workspace", "create", "test-ws", "--from", "Synthesis", "--to", "Synthesis"]
        + ["--project", project_dir, "--plain"]
    )

    records = plain_records(capsys.readouterr().out)
    assert rc == 0, records
    assert records[-1]["status"] == "refreshed"
    assert records[-1]["workspace_id"] == "test-ws"
    assert "executed_steps" not in records[-1]
    assert len(flow_mocks.flow.instances) == 0
    assert flow_json.read_text() == before


def test_workspace_create_with_half_a_range_is_rejected_on_an_existing_workspace(
    capsys, create_cli_project, manifest_stubs, plain_records, flow_mocks
):
    """`--from` alone is a run selector for `ecc run`; `create` has no such form."""
    project_dir, flow_json = _existing_workspace(
        capsys, create_cli_project, manifest_stubs, flow_mocks
    )
    before = flow_json.read_text()

    rc = cli_main.run(
        ["workspace", "create", "test-ws", "--from", "Floorplan", "--project", project_dir]
        + ["--plain"]
    )

    records = plain_records(capsys.readouterr().out)
    assert rc == 1
    assert records[-1]["error"] == "flow_range_requires_pair"
    assert len(flow_mocks.flow.instances) == 0
    assert flow_json.read_text() == before


def test_workspace_create_rejects_set_on_an_existing_workspace(
    capsys, create_cli_project, manifest_stubs, plain_records, flow_mocks
):
    """Issue #442: --set was accepted and dropped; `ecc run --set` rejects it."""
    project_dir, flow_json = _existing_workspace(
        capsys, create_cli_project, manifest_stubs, flow_mocks
    )
    before = flow_json.read_text()

    rc = cli_main.run(
        ["workspace", "create", "test-ws", "--set", "place.target_density=0.5"]
        + ["--project", project_dir, "--plain"]
    )

    records = plain_records(capsys.readouterr().out)
    assert rc == 1
    assert records[-1]["error"] == "set_requires_fresh_run"
    assert records[-1]["workspace_id"] == "test-ws"
    assert len(flow_mocks.flow.instances) == 0
    assert flow_json.read_text() == before


def test_workspace_create_retry_with_the_same_command_id_and_set_is_not_rejected(
    capsys, create_cli_project, manifest_stubs, plain_records, flow_mocks
):
    """A retry of the command that created the workspace is not a new --set request."""
    from chipcompiler.cli.project.run_prepare import create_command_spec
    from chipcompiler.engine.workspace_lifecycle import (
        workspace_command_fingerprint,
        write_workspace_command,
    )

    project_dir, flow_json = _existing_workspace(
        capsys, create_cli_project, manifest_stubs, flow_mocks
    )
    command_id = "0b0f6f0e-7a55-4a4e-9a57-0d6a3f1f6c11"
    request = SimpleNamespace(from_step=None, to_step=None, param_set=("place.target_density=0.5",))
    write_workspace_command(
        flow_json.parent.parent,
        command_id,
        workspace_command_fingerprint("create", create_command_spec(request, "test-ws"), None),
        "test-ws",
        1,
    )
    before = flow_json.read_text()

    def create(value, identity):
        rc = cli_main.run(
            ["workspace", "create", "test-ws", "--set", f"place.target_density={value}"]
            + ["--command-id", identity, "--project", project_dir, "--plain"]
        )
        return rc, plain_records(capsys.readouterr().out)[-1]

    rc, record = create("0.5", command_id)
    assert rc == 0, record
    assert record["status"] == "refreshed"

    rc, record = create("0.6", command_id)
    assert rc == 1
    assert record["error"] == "set_requires_fresh_run"

    rc, record = create("0.5", "5d3c1c62-0a53-4a43-8a44-4a2f5c7f1b90")
    assert rc == 1
    assert record["error"] == "set_requires_fresh_run"

    assert len(flow_mocks.flow.instances) == 0
    assert flow_json.read_text() == before
