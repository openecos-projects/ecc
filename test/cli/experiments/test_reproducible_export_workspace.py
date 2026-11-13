import json
import tarfile

import pytest
from typer.testing import CliRunner

from chipcompiler.cli.app import app
from chipcompiler.project.manifest import MANIFEST_FILENAME


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


def _make_workspace(directory):
    (directory / "home").mkdir(parents=True)
    (directory / "home" / "flow.json").write_text(json.dumps({"steps": []}))


@pytest.fixture
def manifest_project(tmp_path):
    """A manifest project that declares one workspace, ``probe``."""
    project = tmp_path / "project"
    _make_workspace(project / "probe")
    (project / "rtl").mkdir()
    _write_manifest(project, [("probe", project / "probe")])
    return project


def _export(project, output, *args):
    return CliRunner().invoke(
        app, ["reproducible", "export", "--project", str(project), "--output", str(output), *args]
    )


def _rejected(result, output, kind):
    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.startswith(f"{kind}: ")
    assert not output.exists()


def test_declared_workspace_is_exported(manifest_project, tmp_path):
    output = tmp_path / "evidence.tar.gz"

    result = _export(manifest_project, output, "--workspace", "probe")

    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "success"
    with tarfile.open(output) as archive:
        assert "./probe/home/flow.json" in archive.getnames()


def test_omitted_workspace_selects_the_only_declared_workspace(manifest_project, tmp_path):
    output = tmp_path / "evidence.tar.gz"

    result = _export(manifest_project, output)

    assert result.exit_code == 0
    with tarfile.open(output) as archive:
        assert "./probe/home/flow.json" in archive.getnames()


def test_omitted_workspace_is_required_when_several_are_declared(manifest_project, tmp_path):
    _make_workspace(manifest_project / "second")
    _write_manifest(
        manifest_project,
        [("probe", manifest_project / "probe"), ("second", manifest_project / "second")],
    )
    output = tmp_path / "evidence.tar.gz"

    _rejected(_export(manifest_project, output), output, "workspace_required")


def test_undeclared_workspace_is_rejected(manifest_project, tmp_path):
    output = tmp_path / "evidence.tar.gz"

    result = _export(manifest_project, output, "--workspace", "nosuch")

    _rejected(result, output, "workspace_not_declared")
    assert "declared workspaces: probe" in result.stderr


def test_existing_directory_that_is_not_a_workspace_is_rejected(manifest_project, tmp_path):
    output = tmp_path / "evidence.tar.gz"

    _rejected(
        _export(manifest_project, output, "--workspace", "rtl"), output, "workspace_not_declared"
    )


@pytest.mark.parametrize("selector", ["../outside", ""])
def test_name_that_is_not_a_single_name_is_rejected(manifest_project, tmp_path, selector):
    (tmp_path / "outside").mkdir()
    output = tmp_path / "evidence.tar.gz"

    _rejected(
        _export(manifest_project, output, "--workspace", selector), output, "invalid_workspace"
    )


def test_undeclared_absolute_path_is_rejected(manifest_project, tmp_path):
    outside = tmp_path / "outside"
    _make_workspace(outside)
    output = tmp_path / "evidence.tar.gz"

    _rejected(
        _export(manifest_project, output, "--workspace", str(outside)),
        output,
        "workspace_not_declared",
    )


def test_corrupt_manifest_is_reported(manifest_project, tmp_path):
    (manifest_project / MANIFEST_FILENAME).write_text("{not-json")
    output = tmp_path / "evidence.tar.gz"

    _rejected(_export(manifest_project, output, "--workspace", "probe"), output, "manifest_invalid")


def test_project_without_manifest_keeps_the_directory_convention(tmp_path):
    project = tmp_path / "legacy"
    _make_workspace(project / "default")
    output = tmp_path / "evidence.tar.gz"

    result = _export(project, output)

    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "success"
