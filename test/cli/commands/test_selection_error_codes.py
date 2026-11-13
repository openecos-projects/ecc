"""A workspace selection failure is reported under the code of its reason (#423)."""

from pathlib import Path

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.core.records import SELECTION_ERROR_KINDS, manifest_error_record


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


@pytest.mark.parametrize("kind", sorted(SELECTION_ERROR_KINDS))
def test_manifest_error_record_keeps_every_selection_kind(kind):
    record = manifest_error_record(f"{kind}: details")

    assert record["error"] == kind
    assert record["reason"] == f"{kind}: details"


def test_manifest_error_record_falls_back_for_an_unknown_kind():
    assert manifest_error_record("something else happened")["error"] == "workspace_not_declared"
    assert manifest_error_record("")["error"] == "workspace_not_declared"


def _selection_arguments(command, selector, project):
    """One invocation per command family that reports the recorded selection error."""
    if command in LIFECYCLE_COMMANDS:
        return ["workspace", command, selector, "--project", str(project)]
    return [*command.split(), "--project", str(project), "--workspace", selector]


PATH_SELECTION_COMMANDS = [*LIFECYCLE_COMMANDS, "report step", "status"]


@pytest.mark.parametrize("command", PATH_SELECTION_COMMANDS)
def test_absolute_path_that_conflicts_with_a_declared_id_keeps_its_code(
    capsys, manifest_project, plain_records, tmp_path, command
):
    # Same last component as the declared `baseline`, but a different location.
    elsewhere = tmp_path / "elsewhere" / "baseline"
    elsewhere.parent.mkdir()

    rc, record = _error(
        capsys, plain_records, _selection_arguments(command, str(elsewhere), manifest_project)
    )

    assert rc == 1
    assert record["error"] == "workspace_id_conflict"
    assert record["reason"].startswith("workspace_id_conflict: ")


@pytest.mark.parametrize("command", PATH_SELECTION_COMMANDS)
def test_unsafe_absolute_path_keeps_its_code(capsys, manifest_project, plain_records, command):
    # The project directory itself is never a workspace.
    rc, record = _error(
        capsys,
        plain_records,
        _selection_arguments(command, str(manifest_project), manifest_project),
    )

    assert rc == 1
    assert record["error"] == "workspace_path_unsafe"
    assert record["reason"].startswith("workspace_path_unsafe: ")
