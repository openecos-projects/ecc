import json

import pytest
from typer.testing import CliRunner

from chipcompiler.cli.app import app
from chipcompiler.cli.experiments import operations
from chipcompiler.project.manifest import MANIFEST_FILENAME

FAILED_FLOW = {"steps": [{"name": "Synthesis", "tool": "yosys", "state": "Failed"}]}


def _write_manifest(project, workspaces):
    document = {
        "schema_version": 1,
        "design_name": "gcd",
        "root_path": str(project),
        "workspaces": [
            {"workspace_id": name, "workspace_path": str(path)} for name, path in workspaces
        ],
    }
    (project / MANIFEST_FILENAME).write_text(json.dumps(document))


@pytest.fixture
def manifest_project(tmp_path):
    """A manifest project that declares one workspace, ``probe``."""
    project = tmp_path / "project"
    (project / "probe" / "home").mkdir(parents=True)
    _write_manifest(project, [("probe", project / "probe")])
    return project


@pytest.fixture
def external_workspace(tmp_path, manifest_project):
    """Declare ``ext``, whose directory is outside the project and has a failed flow."""
    outside = tmp_path / "outside"
    (outside / "home").mkdir(parents=True)
    (outside / "home" / "flow.json").write_text(json.dumps(FAILED_FLOW))
    _write_manifest(manifest_project, [("probe", manifest_project / "probe"), ("ext", outside)])
    return outside


def _diagnose(project, *args):
    return CliRunner().invoke(app, ["diagnose", "run", "--project", str(project), *args])


def _error(result):
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    return payload


def test_undeclared_workspace_is_rejected_like_status(manifest_project):
    result = _diagnose(manifest_project, "--workspace", "nosuch", "--json")

    assert result.exit_code == 1
    payload = _error(result)
    assert payload["error"] == "workspace_not_declared"
    assert payload["reason"] == (
        "workspace_not_declared: unknown workspace 'nosuch'; declared workspaces: probe"
    )


def test_undeclared_workspace_text_output_goes_to_stderr(manifest_project):
    result = _diagnose(manifest_project, "--workspace", "nosuch")

    assert result.exit_code == 1
    assert "workspace_not_declared" in result.stderr
    assert result.stdout == ""


def test_omitted_workspace_selects_the_only_declared_workspace(manifest_project):
    result = _diagnose(manifest_project, "--json")

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "attention"
    assert payload["workspace"] == str(manifest_project / "probe")


def test_declared_workspace_keeps_its_diagnosis_and_exit_code(manifest_project):
    (manifest_project / "probe" / "home" / "flow.json").write_text(json.dumps(FAILED_FLOW))

    result = _diagnose(manifest_project, "--workspace", "probe", "--json")

    assert result.exit_code == 6
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["workspace"] == str(manifest_project / "probe")
    assert payload["next_actions"] == [
        f"ecc report checklist --project {manifest_project} --workspace probe",
        f"ecc run --project {manifest_project} --workspace probe --resume",
    ]


def test_explicit_default_is_still_checked_against_the_manifest(manifest_project):
    result = _diagnose(manifest_project, "--workspace", "default", "--json")

    assert result.exit_code == 1
    assert _error(result)["error"] == "workspace_not_declared"


def test_omitted_workspace_is_required_when_several_are_declared(
    manifest_project, external_workspace
):
    result = _diagnose(manifest_project, "--json")

    assert result.exit_code == 1
    assert _error(result)["error"] == "workspace_required"


def test_declared_id_reads_the_declared_directory(manifest_project, external_workspace):
    by_id = _diagnose(manifest_project, "--workspace", "ext", "--json")
    by_path = _diagnose(manifest_project, "--workspace", str(external_workspace), "--json")

    assert by_id.exit_code == by_path.exit_code == 6
    for result in (by_id, by_path):
        payload = json.loads(result.stdout)
        assert payload["status"] == "failed"
        assert payload["workspace"] == str(external_workspace)
        assert payload["flow"]["failed_steps"] == ["Synthesis"]
    assert "--workspace ext" in json.loads(by_id.stdout)["next_actions"][0]


def test_undeclared_absolute_path_is_rejected(tmp_path, manifest_project):
    stray = tmp_path / "stray"
    stray.mkdir()

    result = _diagnose(manifest_project, "--workspace", str(stray), "--json")

    assert result.exit_code == 1
    assert _error(result)["error"] == "workspace_not_declared"


def test_unreadable_manifest_is_reported(manifest_project):
    (manifest_project / MANIFEST_FILENAME).write_text("{broken")

    result = _diagnose(manifest_project, "--workspace", "probe", "--json")

    assert result.exit_code == 1
    assert _error(result)["error"] == "manifest_invalid"


def test_project_without_manifest_keeps_directory_convention(tmp_path):
    assert operations.select_experiment_workspace(tmp_path, None) == ("default", None, None)
    assert operations.select_experiment_workspace(tmp_path, "ws_1") == ("ws_1", None, None)

    result = _diagnose(tmp_path, "--workspace", "ws_1", "--json")

    assert result.exit_code == 0
    assert json.loads(result.stdout)["workspace"] == str(tmp_path / "ws_1")
