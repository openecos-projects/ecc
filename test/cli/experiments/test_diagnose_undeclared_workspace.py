import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from chipcompiler.cli.app import app
from chipcompiler.cli.experiments import operations
from chipcompiler.project.manifest import MANIFEST_FILENAME, ManifestError


@pytest.fixture
def manifest_project(tmp_path, monkeypatch):
    """A project whose manifest declares one workspace, ``probe``."""
    project = tmp_path / "project"
    (project / "probe" / "home").mkdir(parents=True)
    (project / MANIFEST_FILENAME).write_text("{}")
    declared = SimpleNamespace(
        workspace_id="probe", workspace_path=str(project / "probe"), status="active"
    )
    manifest = SimpleNamespace(
        workspaces=(declared,),
        active_workspaces=lambda: [declared],
        find_workspace=lambda name: declared if name == "probe" else None,
    )
    monkeypatch.setattr(operations, "load_manifest", lambda _project: manifest)
    return project


def _diagnose(project, workspace, *flags):
    return CliRunner().invoke(
        app, ["diagnose", "run", "--project", str(project), "--workspace", workspace, *flags]
    )


def test_undeclared_workspace_reason_names_the_declared_workspaces(manifest_project):
    reason = operations.undeclared_workspace_reason(manifest_project, "nosuch")

    assert reason == (
        "workspace_not_declared: unknown workspace 'nosuch'; declared workspaces: probe"
    )


def test_declared_workspace_is_accepted_by_id_and_by_path(manifest_project):
    assert operations.undeclared_workspace_reason(manifest_project, "probe") is None
    assert (
        operations.undeclared_workspace_reason(manifest_project, str(manifest_project / "probe"))
        is None
    )


def test_project_without_manifest_is_not_checked(tmp_path):
    assert operations.undeclared_workspace_reason(tmp_path, "nosuch") is None


def test_unreadable_manifest_is_not_checked(tmp_path, monkeypatch):
    (tmp_path / MANIFEST_FILENAME).write_text("{broken")

    def fail(_project):
        raise ManifestError("invalid project manifest")

    monkeypatch.setattr(operations, "load_manifest", fail)

    assert operations.undeclared_workspace_reason(tmp_path, "nosuch") is None


def test_diagnose_run_json_rejects_undeclared_workspace(manifest_project):
    result = _diagnose(manifest_project, "nosuch", "--json")

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["error"] == "workspace_not_declared"
    assert "declared workspaces: probe" in payload["reason"]


def test_diagnose_run_text_rejects_undeclared_workspace(manifest_project):
    result = _diagnose(manifest_project, "nosuch")

    assert result.exit_code == 1
    assert "workspace_not_declared" in result.output
    assert "status:" not in result.output


def test_diagnose_run_still_reports_a_declared_workspace(manifest_project):
    result = _diagnose(manifest_project, "probe", "--json")

    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "attention"
