import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chipcompiler.cli.app import app

runner = CliRunner()


@pytest.fixture
def exported_case(create_cli_project, create_flow_json, tmp_path):
    project = Path(create_cli_project(tmp_path / "project"))
    workspace = project / "sample"
    create_flow_json(str(workspace))
    store = tmp_path / "source-store"
    result = runner.invoke(
        app,
        [
            "experience",
            "collect",
            "--project",
            str(project),
            "--workspace",
            "sample",
            "--store",
            str(store),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    return store, json.loads(result.stdout)[0]["case_id"]


def test_transfer_commands_work_outside_projects(exported_case, tmp_path, monkeypatch):
    store, case_id = exported_case
    monkeypatch.chdir(tmp_path)
    package = tmp_path / "case.tar.gz"
    exported = runner.invoke(
        app,
        [
            "experience",
            "export",
            "--store",
            str(store),
            "--case-id",
            case_id,
            "--output",
            str(package),
            "--json",
        ],
    )
    assert exported.exit_code == 0, exported.output
    target = tmp_path / "target-store"
    imported = runner.invoke(
        app, ["experience", "import", "--store", str(target), "--package", str(package), "--json"]
    )
    assert imported.exit_code == 0, imported.output
    assert (
        json.loads(imported.stdout)[0]["package_id"] == json.loads(exported.stdout)[0]["package_id"]
    )
    repeated = runner.invoke(
        app, ["experience", "import", "--store", str(target), "--package", str(package), "--plain"]
    )
    assert repeated.exit_code == 0, repeated.output
    assert "already_present" in repeated.stdout


def test_corrupt_package_preserves_json_and_exit_code(tmp_path):
    package = tmp_path / "bad.tar.gz"
    package.write_bytes(b"invalid")
    result = runner.invoke(
        app,
        [
            "experience",
            "import",
            "--store",
            str(tmp_path / "store"),
            "--package",
            str(package),
            "--json",
        ],
    )
    assert result.exit_code == 6, result.output
    assert json.loads(result.stdout)[0]["error"] == "experience_package_invalid"
    assert not (tmp_path / "store").exists()


def test_export_without_selection_is_usage_error(tmp_path):
    result = runner.invoke(
        app,
        [
            "experience",
            "export",
            "--store",
            str(tmp_path / "store"),
            "--output",
            str(tmp_path / "out.tar.gz"),
            "--json",
        ],
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.stdout)[0]["error"] == "experience_package_selection_invalid"


def test_import_busy_store_uses_existing_exit_code(exported_case, tmp_path):
    store, case_id = exported_case
    package = tmp_path / "case.tar.gz"
    exported = runner.invoke(
        app,
        [
            "experience",
            "export",
            "--store",
            str(store),
            "--case-id",
            case_id,
            "--output",
            str(package),
            "--json",
        ],
    )
    assert exported.exit_code == 0, exported.output
    target = tmp_path / "target-store"
    (target / ".write-lock").mkdir(parents=True)
    result = runner.invoke(
        app, ["experience", "import", "--store", str(target), "--package", str(package), "--json"]
    )
    assert result.exit_code == 20, result.output
    assert json.loads(result.stdout)[0]["error"] == "experience_store_busy"
