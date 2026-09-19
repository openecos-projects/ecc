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


def _write_derived_manifest(workspace_dir, contents: dict):
    """Record the derived-state hashes for the given config file contents."""
    import hashlib

    from chipcompiler.data.workspace.config_manifest import derived_config_manifest_path

    entries = {
        name: {"sha256": hashlib.sha256(content.encode()).hexdigest(), "size": len(content)}
        for name, content in contents.items()
    }
    derived_config_manifest_path(workspace_dir).write_text(json.dumps({"files": entries}))


def test_refresh_proceeds_when_derived_configs_match(
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
    db_path = Path(workspace_dir, "config", "db_ecc.json")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_text("{}")
    _write_derived_manifest(workspace_dir, {"db_ecc.json": "{}"})

    rc = cli_main.run(["workspace", "refresh", "baseline", "--project", project_dir, "--plain"])

    assert rc == 0
    records = plain_records(capsys.readouterr().out)
    assert records[-1]["status"] == "refreshed"


def test_refresh_refuses_and_lists_files_after_hand_edit(
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
    db_path = Path(workspace_dir, "config", "db_ecc.json")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_text('{"RT": {}}')  # hand edit, diverging from the record
    _write_derived_manifest(workspace_dir, {"db_ecc.json": "{}"})

    rc = cli_main.run(["workspace", "refresh", "baseline", "--project", project_dir, "--plain"])

    assert rc == 1
    (record,) = plain_records(capsys.readouterr().out)
    assert record["error"] == "derived_configs_modified"
    assert record["files"] == "db_ecc.json"
    assert "--force" in record["hint"]


def test_refresh_force_overwrites_modified_configs(
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
    db_path = Path(workspace_dir, "config", "db_ecc.json")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_text('{"RT": {}}')
    _write_derived_manifest(workspace_dir, {"db_ecc.json": "{}"})

    rc = cli_main.run(
        ["workspace", "refresh", "baseline", "--force", "--project", project_dir, "--plain"]
    )

    assert rc == 0
    records = plain_records(capsys.readouterr().out)
    assert records[-1]["status"] == "refreshed"
    assert flow_mocks.flow.instances[-1].create_called is True


def test_refresh_surfaces_manifest_write_back_failure(
    capsys,
    create_cli_project,
    create_flow_json,
    flow_mocks,
    manifest_stubs,
    monkeypatch,
    plain_records,
):
    """A failed project.json status write-back is a diagnosable error record
    with a repair command, not a silent warning — and the refresh itself
    still succeeds."""
    project_dir = create_cli_project()
    workspace_dir = os.path.join(project_dir, "baseline")
    project_path = Path(project_dir)
    manifest_stubs.write(project_path, [manifest_stubs.entry(project_path, "baseline")])
    create_flow_json(workspace_dir)

    monkeypatch.setattr(
        "chipcompiler.project.manifest_write.write_back_workspace_status",
        lambda *args, **kwargs: False,
    )

    rc = cli_main.run(["workspace", "refresh", "baseline", "--project", project_dir, "--plain"])

    assert rc == 0
    records = plain_records(capsys.readouterr().out)
    assert records[-1]["status"] == "refreshed"
    failure = [record for record in records if record.get("error") == "manifest_write_back_failed"]
    assert len(failure) == 1
    assert failure[0]["lost_status"] == "not_started"
    assert failure[0]["repair"].startswith("ecc run")
