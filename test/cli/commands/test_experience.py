import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chipcompiler.cli.app import app

runner = CliRunner()


@pytest.fixture
def legacy_project(create_cli_project, create_flow_json):
    from pathlib import Path

    project = Path(create_cli_project())
    workspace = project / "sample-workspace"
    create_flow_json(str(workspace))
    return project, workspace


def test_experience_collect_uses_current_workspace_defaults(legacy_project, tmp_path, monkeypatch):
    project, workspace = legacy_project
    monkeypatch.chdir(workspace)
    result = runner.invoke(
        app, ["experience", "collect", "--store", str(tmp_path / "store"), "--json"]
    )
    assert result.exit_code == 0, result.output
    record = json.loads(result.stdout)[0]
    assert record["status"] == "created"
    assert record["source"]["workspace_root"] == str(workspace)
    assert record["validation_scope"] == "legacy_import"
    assert not (workspace / "home/engineering-snapshot.json").exists()


def test_experience_store_commands_work_outside_project(legacy_project, tmp_path, monkeypatch):
    project, workspace = legacy_project
    store_args = ["--store", str(tmp_path / "store"), "--json"]
    collected = runner.invoke(
        app,
        [
            "experience",
            "collect",
            "--project",
            str(project),
            "--workspace",
            workspace.name,
            *store_args,
        ],
    )
    assert collected.exit_code == 0, collected.output
    case_id = json.loads(collected.stdout)[0]["case_id"]
    monkeypatch.chdir(tmp_path)
    listing = runner.invoke(app, ["experience", "list", *store_args])
    assert listing.exit_code == 0
    assert [item["case_id"] for item in json.loads(listing.stdout)] == [case_id]
    shown = runner.invoke(app, ["experience", "show", case_id, *store_args])
    assert shown.exit_code == 0
    assert json.loads(shown.stdout)[0]["case_id"] == case_id
    verification = runner.invoke(app, ["experience", "verify", case_id, *store_args])
    assert verification.exit_code == 7
    assert json.loads(verification.stdout)[0]["status"] == "unknown"


def test_experience_verify_preserves_json_on_corrupt_case(legacy_project, tmp_path):
    project, workspace = legacy_project
    store = tmp_path / "store"
    args = ["--store", str(store), "--json"]
    result = runner.invoke(
        app,
        [
            "experience",
            "collect",
            "--project",
            str(project),
            "--workspace",
            workspace.name,
            *args,
        ],
    )
    assert result.exit_code == 0
    case_id = json.loads(result.stdout)[0]["case_id"]
    (store / "cases" / case_id / "case.json").write_text("{")
    result = runner.invoke(app, ["experience", "verify", *args])
    assert result.exit_code == 6
    assert json.loads(result.stdout)[0]["status"] == "fail"


def test_experience_busy_workspace_returns_20(legacy_project, tmp_path):
    project, workspace = legacy_project
    (workspace / "home/flow.json").write_text('{"steps": [{"state": "Ongoing"}]}')
    result = runner.invoke(
        app,
        [
            "experience",
            "collect",
            "--project",
            str(project),
            "--workspace",
            workspace.name,
            "--store",
            str(tmp_path / "store"),
            "--json",
        ],
    )
    assert result.exit_code == 20
    assert json.loads(result.stdout)[0]["error"] == "experience_workspace_busy"


def test_experience_json_plain_conflict_returns_usage_error(tmp_path):
    result = runner.invoke(
        app,
        [
            "experience",
            "list",
            "--store",
            str(tmp_path),
            "--json",
            "--plain",
        ],
    )
    assert result.exit_code == 2


def test_experience_recording_enable_status_disable(create_cli_project, tmp_path):
    project = create_cli_project()
    store = tmp_path / "experience-store"

    enabled = runner.invoke(
        app,
        [
            "experience",
            "enable",
            "--project",
            project,
            "--store",
            str(store),
            "--json",
        ],
    )
    assert enabled.exit_code == 0, enabled.output
    assert json.loads(enabled.stdout)[0]["enabled"] is True

    current = runner.invoke(app, ["experience", "status", "--project", project, "--json"])
    assert current.exit_code == 0, current.output
    payload = json.loads(current.stdout)[0]
    assert payload["configured"] is True
    assert payload["store"] == str(store.resolve())
    assert payload["outbox"]["pending"] == 0

    disabled = runner.invoke(app, ["experience", "disable", "--project", project, "--json"])
    assert disabled.exit_code == 0, disabled.output
    assert json.loads(disabled.stdout)[0]["enabled"] is False


def test_experience_recording_rejects_store_inside_project(create_cli_project, tmp_path):
    project = create_cli_project()
    nested_store = Path(project) / "nested-store"
    result = runner.invoke(
        app,
        [
            "experience",
            "enable",
            "--project",
            project,
            "--store",
            str(nested_store),
            "--json",
        ],
    )
    assert result.exit_code == 2
    assert json.loads(result.stdout)[0]["error"] == "experience_project_invalid"


@pytest.mark.parametrize("command", ["show", "verify"])
def test_experience_rejects_invalid_case_id_as_usage_error(tmp_path, command):
    result = runner.invoke(
        app,
        [
            "experience",
            command,
            "../outside",
            "--store",
            str(tmp_path),
            "--json",
        ],
    )
    assert result.exit_code == 2
    assert json.loads(result.stdout)[0]["error"] == "experience_case_id_invalid"
