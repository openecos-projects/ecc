"""A workspace selection failure is reported under the code of its reason (#423)."""

from pathlib import Path

import pytest

from chipcompiler.cli import main as cli_main


@pytest.fixture
def manifest_project(create_cli_project, manifest_stubs):
    """A manifest project that declares one workspace, ``baseline``."""
    project = Path(create_cli_project())
    manifest_stubs.write(project, [manifest_stubs.entry(project, "baseline")])
    return project


def _error(capsys, plain_records, arguments):
    rc = cli_main.run([*arguments, "--plain"])
    (record,) = [r for r in plain_records(capsys.readouterr().out) if "error" in r]
    return rc, record


LIFECYCLE_COMMANDS = ["archive", "delete", "reset-flow"]


@pytest.mark.parametrize("command", LIFECYCLE_COMMANDS)
def test_lifecycle_command_reports_a_corrupt_manifest(
    capsys, manifest_project, plain_records, command
):
    (manifest_project / "project.json").write_text("{not-json")

    rc, record = _error(
        capsys,
        plain_records,
        ["workspace", command, "baseline", "--project", str(manifest_project)],
    )

    assert rc == 1
    assert record["error"] == "manifest_invalid"
    assert record["reason"].startswith("manifest_invalid: ")


@pytest.mark.parametrize("command", LIFECYCLE_COMMANDS)
@pytest.mark.parametrize("name", ["../escape", ""])
def test_lifecycle_command_reports_an_invalid_name(
    capsys, manifest_project, plain_records, command, name
):
    rc, record = _error(
        capsys, plain_records, ["workspace", command, name, "--project", str(manifest_project)]
    )

    assert rc == 1
    assert record["error"] == "invalid_workspace"
    assert record["reason"].startswith("invalid_workspace: ")


@pytest.mark.parametrize("command", LIFECYCLE_COMMANDS)
def test_lifecycle_command_still_reports_an_undeclared_workspace(
    capsys, manifest_project, plain_records, command
):
    rc, record = _error(
        capsys, plain_records, ["workspace", command, "nosuch", "--project", str(manifest_project)]
    )

    assert rc == 1
    assert record["error"] == "workspace_not_declared"
    assert "declared workspaces: baseline" in record["reason"]


def test_report_step_reports_an_undeclared_workspace(capsys, manifest_project, plain_records):
    rc, record = _error(
        capsys,
        plain_records,
        ["report", "step", "--project", str(manifest_project), "--workspace", "nosuch"],
    )

    assert rc == 1
    assert record["error"] == "workspace_not_declared"
    assert "declared workspaces: baseline" in record["reason"]


def test_report_step_requires_a_workspace_when_several_are_declared(
    capsys, manifest_project, manifest_stubs, plain_records
):
    manifest_stubs.write(
        manifest_project,
        [
            manifest_stubs.entry(manifest_project, "baseline"),
            manifest_stubs.entry(manifest_project, "second"),
        ],
    )

    rc, record = _error(
        capsys, plain_records, ["report", "step", "--project", str(manifest_project)]
    )

    assert rc == 1
    assert record["error"] == "workspace_required"


def test_report_step_reports_a_corrupt_manifest(capsys, manifest_project, plain_records):
    (manifest_project / "project.json").write_text("{not-json")

    rc, record = _error(
        capsys,
        plain_records,
        ["report", "step", "--project", str(manifest_project), "--workspace", "baseline"],
    )

    assert rc == 1
    assert record["error"] == "manifest_invalid"
    assert "run" not in record


def test_report_step_still_reports_a_declared_workspace_without_a_directory(
    capsys, manifest_project, plain_records
):
    rc, record = _error(
        capsys,
        plain_records,
        ["report", "step", "--project", str(manifest_project), "--workspace", "baseline"],
    )

    assert rc == 1
    assert record["error"] == "missing_workspace"
    assert record["run"].startswith("ecc run")
