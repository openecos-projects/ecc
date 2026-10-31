import json
from copy import deepcopy
from pathlib import Path

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.engine import create_workspace_from_spec
from chipcompiler.engine.snapshot import read_engineering_snapshot_from_directory
from chipcompiler.engine.workspace_lifecycle import (
    workspace_command_fingerprint,
    write_workspace_command,
)
from chipcompiler.project import (
    create_project_manifest,
    load_project_manifest,
    mutate_project_manifest,
)
from chipcompiler.project.locking import flock_file
from chipcompiler.project.manifest_write import manifest_lock


def _register_workspace(project, workspace_id):
    workspace = project / workspace_id
    workspace.mkdir(exist_ok=True)
    (workspace / "unrelated.txt").write_text(workspace_id, encoding="utf-8")
    mutate_project_manifest(
        project,
        {
            "type": "register_workspace",
            "workspace_id": workspace_id,
            "workspace_path": str(workspace),
        },
    )
    return workspace


def _tree_contents(root):
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


@pytest.fixture
def interrupted_delete(tmp_path, minimal_ics55_pdk_factory):
    project = tmp_path / "project"
    create_project_manifest(project, "Project", "gcd")
    fixture = Path(__file__).parents[2] / "fixtures" / "workspace_spec" / "valid.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    bindings = deepcopy(payload["workspaceBindings"])
    bindings["inputs"] = {
        key: str(fixture.parent / value) for key, value in bindings["inputs"].items()
    }
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace = project / "baseline"
    create_workspace_from_spec(workspace, payload["workspaceSpec"], bindings, "create-1")
    _register_workspace(project, "baseline")
    manifest = load_project_manifest(project)
    snapshot = read_engineering_snapshot_from_directory(workspace)
    command_id = "delete-crash-1"
    fingerprint = workspace_command_fingerprint(
        "delete",
        {
            "project": str(project),
            "workspaceId": "baseline",
            "workspace": str(workspace),
            "deleteDirectory": True,
        },
        {},
        snapshot["workspaceRevision"],
    )
    write_workspace_command(
        workspace,
        command_id,
        fingerprint,
        snapshot["workspaceId"],
        snapshot["workspaceRevision"],
        metadata={
            "operation": "delete",
            "projectId": manifest["project_id"],
            "workspaceId": "baseline",
            "workspacePath": str(workspace),
            "phase": "intent",
        },
    )
    staging = project / f".ecc-delete-baseline-{command_id}"
    workspace.rename(staging)
    return project, workspace, staging


@pytest.mark.parametrize("workspace_ids", [(), ("default",), ("default", "derived")])
@pytest.mark.parametrize("explicit_project", [False, True])
def test_reconcile_deletes_does_not_require_workspace_selection(
    tmp_path, monkeypatch, capsys, plain_records, workspace_ids, explicit_project
):
    project = tmp_path / "project"
    create_project_manifest(project, "Project", "gcd")
    for workspace_id in workspace_ids:
        _register_workspace(project, workspace_id)
    before = _tree_contents(project)
    monkeypatch.chdir(tmp_path if explicit_project else project)
    args = ["workspace", "reconcile-deletes", "--plain"]
    if explicit_project:
        args += ["--project", str(project)]

    exit_code = cli_main.run(args)

    output = capsys.readouterr().out
    assert exit_code == 0, output
    assert plain_records(output) == [{"status": "reconciled", "recovered_deletes": "[]"}]
    assert _tree_contents(project) == before


@pytest.mark.parametrize("registered", [False, True])
@pytest.mark.parametrize("other_ids", [(), ("unrelated", "other")])
@pytest.mark.parametrize("explicit_project", [False, True])
def test_reconcile_deletes_recovers_interrupted_delete_and_is_idempotent(
    interrupted_delete, monkeypatch, capsys, plain_records, registered, other_ids, explicit_project
):
    project, workspace, staging = interrupted_delete
    for workspace_id in other_ids:
        _register_workspace(project, workspace_id)
    if not registered:
        mutate_project_manifest(project, {"type": "delete_workspace", "workspace_id": "baseline"})
    manifest_before = (project / "project.json").read_bytes()
    unrelated_before = {name: _tree_contents(project / name) for name in other_ids}
    staged_before = _tree_contents(staging)
    monkeypatch.chdir(project.parent if explicit_project else project)
    args = ["workspace", "reconcile-deletes", "--plain"]
    if explicit_project:
        args += ["--project", str(project)]

    exit_code = cli_main.run(args)

    output = capsys.readouterr().out
    assert exit_code == 0, output
    action = "restored" if registered else "removed"
    assert plain_records(output) == [
        {"status": "reconciled", "recovered_deletes": f"[{action}:baseline]"}
    ]
    assert not staging.exists()
    assert workspace.exists() is registered
    if registered:
        assert _tree_contents(workspace) == staged_before
    assert (project / "project.json").read_bytes() == manifest_before
    assert {name: _tree_contents(project / name) for name in other_ids} == unrelated_before

    recovered_before = _tree_contents(project)
    assert cli_main.run(args) == 0
    assert plain_records(capsys.readouterr().out) == [
        {"status": "reconciled", "recovered_deletes": "[]"}
    ]
    assert _tree_contents(project) == recovered_before


@pytest.mark.parametrize("invalid_manifest", ["invalid-json", "schema-version", "root-path"])
def test_reconcile_deletes_still_validates_manifest(
    interrupted_delete, capsys, plain_records, invalid_manifest
):
    project, workspace, staging = interrupted_delete
    manifest_path = project / "project.json"
    manifest = load_project_manifest(project)
    if invalid_manifest == "invalid-json":
        manifest_path.write_text("{", encoding="utf-8")
    else:
        if invalid_manifest == "schema-version":
            manifest["schema_version"] = 2
        else:
            manifest["root_path"] = str(project.parent)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    before = _tree_contents(project)

    exit_code = cli_main.run(
        ["workspace", "reconcile-deletes", "--project", str(project), "--plain"]
    )

    output = capsys.readouterr().out
    assert exit_code == 1, output
    assert plain_records(output)[0]["error"] == "manifest_invalid"
    assert not workspace.exists()
    assert staging.is_dir()
    assert _tree_contents(project) == before


@pytest.mark.parametrize(
    ("corruption", "expected_error"),
    [
        ("missing-ledger", "workspace_delete_recovery_unproven"),
        ("project-id", "workspace_delete_recovery_unproven"),
        ("fingerprint", "workspace_delete_recovery_unproven"),
        ("outside-path", "workspace_delete_recovery_unsafe"),
        ("existing-target", "workspace_delete_recovery_ambiguous"),
    ],
)
def test_reconcile_deletes_preserves_unsafe_or_ambiguous_staging(
    interrupted_delete, capsys, plain_records, corruption, expected_error
):
    project, workspace, staging = interrupted_delete
    _register_workspace(project, "unrelated")
    ledger_path = staging / "home" / "workspace-commands.json"
    if corruption == "missing-ledger":
        ledger_path.unlink()
    elif corruption == "existing-target":
        workspace.mkdir()
        (workspace / "keep.txt").write_text("keep", encoding="utf-8")
    else:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        command = ledger["commands"]["delete-crash-1"]
        if corruption == "project-id":
            command["metadata"]["projectId"] = "another-project"
        elif corruption == "fingerprint":
            command["fingerprint"] = "invalid-fingerprint"
        else:
            command["metadata"]["workspacePath"] = str(project.parent / "baseline")
        ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    before = _tree_contents(project)

    exit_code = cli_main.run(
        ["workspace", "reconcile-deletes", "--project", str(project), "--plain"]
    )

    output = capsys.readouterr().out
    assert exit_code == 1, output
    assert plain_records(output)[0]["error"] == expected_error
    assert staging.is_dir()
    assert _tree_contents(project) == before


@pytest.mark.parametrize("lock_kind", ["workspace", "manifest"])
def test_reconcile_deletes_no_wait_preserves_busy_workspace(
    interrupted_delete, capsys, plain_records, lock_kind
):
    project, workspace, staging = interrupted_delete
    _register_workspace(project, "unrelated")
    lock = (
        flock_file(str(project / "baseline.lock"), blocking=False)
        if lock_kind == "workspace"
        else manifest_lock(project, blocking=False)
    )
    with lock:
        before = _tree_contents(project)

        exit_code = cli_main.run(
            ["workspace", "reconcile-deletes", "--project", str(project), "--no-wait", "--plain"]
        )

    output = capsys.readouterr().out
    assert exit_code == 20, output
    assert plain_records(output)[0]["error"] == "workspace_busy"
    assert not workspace.exists()
    assert staging.is_dir()
    assert _tree_contents(project) == before
