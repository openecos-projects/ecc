"""A command repeated with the same --command-id is a retry, with or without
--expected-revision (#473)."""

import json
from pathlib import Path

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.engine import create_workspace_from_spec
from chipcompiler.engine.snapshot.store import read_engineering_snapshot_from_directory
from chipcompiler.project import mutate_project_manifest

COMMANDS = {
    "reset-flow": ["workspace", "reset-flow", "w"],
    "param-apply": ["param", "apply", "--workspace", "w", "--set", "cts.skew_bound=0.10"],
}


@pytest.fixture
def project(tmp_path, minimal_ics55_pdk_factory):
    """A project with one managed workspace, ``w``, at revision 1."""
    project_dir = tmp_path / "project"
    assert cli_main.run(["init", str(project_dir), "--design-name", "gcd"]) == 0
    fixture = Path(__file__).parents[2] / "fixtures" / "workspace_spec" / "valid.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    bindings = payload["workspaceBindings"]
    bindings["inputs"] = {
        key: str(fixture.parent / value) for key, value in bindings["inputs"].items()
    }
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    create_workspace_from_spec(project_dir / "w", payload["workspaceSpec"], bindings, "create-1")
    mutate_project_manifest(
        project_dir,
        {
            "type": "register_workspace",
            "workspace_id": "w",
            "workspace_path": str(project_dir / "w"),
        },
    )
    return project_dir


@pytest.fixture
def ecc(project, capsys, plain_records):
    def run(command: list[str], *options: str) -> tuple[int, dict]:
        capsys.readouterr()
        rc = cli_main.run([*command, *options, "--project", str(project), "--plain"])
        return rc, plain_records(capsys.readouterr().out)[-1]

    return run


def _revision(project: Path) -> int:
    return read_engineering_snapshot_from_directory(project / "w")["workspaceRevision"]


@pytest.mark.parametrize("command", COMMANDS.values(), ids=COMMANDS.keys())
def test_command_repeated_with_its_command_id_is_replayed(project, ecc, command):
    rc, first = ecc(command, "--command-id", "retry-1")
    assert rc == 0
    assert _revision(project) == 2

    rc, repeated = ecc(command, "--command-id", "retry-1")

    assert rc == 0
    assert repeated == first
    # Replayed, not applied a second time.
    assert _revision(project) == 2


@pytest.mark.parametrize("command", COMMANDS.values(), ids=COMMANDS.keys())
def test_retry_is_replayed_after_the_workspace_moved_on(project, ecc, command):
    assert ecc(command, "--command-id", "retry-1")[0] == 0
    assert ecc(["workspace", "reset-flow", "w"])[0] == 0
    assert _revision(project) == 3

    rc, _record = ecc(command, "--command-id", "retry-1")

    assert rc == 0
    assert _revision(project) == 3


def test_command_id_reused_for_a_different_request_is_a_conflict(project, ecc):
    assert ecc(COMMANDS["param-apply"], "--command-id", "retry-1")[0] == 0

    different = ["param", "apply", "--workspace", "w", "--set", "cts.skew_bound=0.20"]
    rc, record = ecc(different, "--command-id", "retry-1")
    assert rc == 1
    assert record["error"] == "idempotency_conflict"

    rc, record = ecc(COMMANDS["reset-flow"], "--command-id", "retry-1")
    assert rc == 1
    assert record["error"] == "idempotency_conflict"
    assert _revision(project) == 2


@pytest.mark.parametrize("command", COMMANDS.values(), ids=COMMANDS.keys())
def test_named_revision_stays_part_of_the_request(project, ecc, command):
    pinned = ("--command-id", "retry-1", "--expected-revision")
    assert ecc(command, *pinned, "1")[0] == 0
    assert ecc(command, *pinned, "1")[0] == 0
    assert _revision(project) == 2

    # The same id with another revision, or with none, is another request.
    for options in ((*pinned, "2"), ("--command-id", "retry-1")):
        rc, record = ecc(command, *options)
        assert rc == 1
        assert record["error"] == "idempotency_conflict"
    assert _revision(project) == 2


@pytest.mark.parametrize("command", COMMANDS.values(), ids=COMMANDS.keys())
def test_stale_named_revision_is_still_a_revision_conflict(project, ecc, command):
    assert ecc(command)[0] == 0

    rc, record = ecc(command, "--command-id", "retry-1", "--expected-revision", "1")

    assert rc == 21
    assert record["error"] == "revision_conflict"
    assert _revision(project) == 2
