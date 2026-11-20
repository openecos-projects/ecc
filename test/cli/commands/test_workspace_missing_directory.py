"""A declared workspace whose directory has been removed (#471)."""

import json
from pathlib import Path

import pytest

from chipcompiler.cli import main as cli_main


@pytest.fixture
def project(create_cli_project, manifest_stubs):
    """A project that declares ``gone`` (no directory) and ``kept``."""
    project_dir = Path(create_cli_project())
    kept = manifest_stubs.entry(project_dir, "kept")
    kept["source_workspace_id"] = "gone"
    manifest_stubs.write(
        project_dir,
        [manifest_stubs.entry(project_dir, "gone"), kept],
        best_workspace={"workspace_id": "gone"},
    )
    (project_dir / "kept").mkdir()
    return project_dir


def _declared(project_dir: Path) -> list[str]:
    document = json.loads((project_dir / "project.json").read_text())
    return [entry["workspace_id"] for entry in document["workspaces"]]


@pytest.mark.parametrize(
    "options",
    [[], ["--delete-directory"], ["--expected-revision", "3", "--command-id", "retry-1"]],
    ids=["plain", "delete-directory", "revision-and-command-id"],
)
def test_delete_unregisters_a_workspace_without_a_directory(
    project, capsys, plain_records, options
):
    arguments = ["workspace", "delete", "gone", *options, "--project", str(project), "--plain"]

    assert cli_main.run(arguments) == 0

    (record,) = plain_records(capsys.readouterr().out)
    assert record["workspace_id"] == "gone"
    assert record["status"] == "deleted"
    document = json.loads((project / "project.json").read_text())
    assert _declared(project) == ["kept"]
    # The references to the removed entry go with it, as in any delete.
    assert document["workspaces"][0]["source_workspace_id"] is None
    assert document["best_workspace"] is None
    assert not (project / "gone").exists()
    assert (project / "kept").is_dir()


def test_delete_of_a_missing_directory_still_refuses_a_registered_process(
    project, capsys, plain_records
):
    path = project / "project.json"
    document = json.loads(path.read_text())
    document["runtime_processes"] = {"gone": {"run_id": "active"}}
    path.write_text(json.dumps(document))

    rc = cli_main.run(["workspace", "delete", "gone", "--project", str(project), "--plain"])

    assert rc == 1
    (record,) = plain_records(capsys.readouterr().out)
    assert record["error"] == "workspace_running"
    assert _declared(project) == ["gone", "kept"]


@pytest.mark.parametrize(
    "command",
    [["archive"], ["reset-flow"], ["refresh"], ["refresh", "--force"]],
    ids=["archive", "reset-flow", "refresh", "refresh-force"],
)
def test_commands_that_need_the_directory_name_the_ways_out(
    project, capsys, plain_records, command
):
    operation, *options = command
    arguments = ["workspace", operation, "gone", *options, "--project", str(project), "--plain"]

    assert cli_main.run(arguments) == 1

    (record,) = plain_records(capsys.readouterr().out)
    assert record["error"] == "workspace_missing"
    assert record["reason"] == f"workspace directory does not exist: {project / 'gone'}"
    assert record["workspace_id"] == "gone"
    assert record["delete_cmd"] == f"ecc workspace delete gone --project {project}"
    assert record["create_cmd"] == f"ecc workspace create gone --project {project}"
    assert _declared(project) == ["gone", "kept"]
    assert not (project / "gone").exists()
