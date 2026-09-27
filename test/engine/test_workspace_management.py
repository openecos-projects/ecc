import json
from copy import deepcopy
from pathlib import Path

import pytest

from chipcompiler.engine import create_workspace_from_spec
from chipcompiler.engine.workspace_lifecycle import WorkspaceLifecycleError
from chipcompiler.engine.workspace_management import (
    archive_managed_workspace,
    delete_managed_workspace,
    reconcile_workspace_deletes,
)
from chipcompiler.project import (
    create_project_manifest,
    load_project_manifest,
    mutate_project_manifest,
)


def _managed_workspace(tmp_path, minimal_ics55_pdk_factory):
    project = tmp_path / "project"
    create_project_manifest(project, "Project", "gcd")
    fixture = Path(__file__).parents[1] / "fixtures" / "workspace_spec" / "valid.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    spec = payload["workspaceSpec"]
    bindings = deepcopy(payload["workspaceBindings"])
    bindings["inputs"] = {
        key: str(fixture.parent / value) for key, value in bindings["inputs"].items()
    }
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    workspace_path = project / "baseline"
    create_workspace_from_spec(workspace_path, spec, bindings, "create-1")
    mutate_project_manifest(
        project,
        {
            "type": "register_workspace",
            "workspace_id": "baseline",
            "workspace_path": str(workspace_path),
        },
    )
    return project, workspace_path


def test_archive_checks_revision_and_updates_only_manifest(tmp_path, minimal_ics55_pdk_factory):
    project, workspace = _managed_workspace(tmp_path, minimal_ics55_pdk_factory)

    archive_managed_workspace(
        project,
        "baseline",
        1,
        command_id="archive-1",
        blocking=True,
    )

    manifest = load_project_manifest(project)
    assert manifest["workspaces"][0]["status"] == "archived"
    assert workspace.is_dir()

    with pytest.raises(WorkspaceLifecycleError) as conflict:
        archive_managed_workspace(
            project,
            "baseline",
            2,
            command_id="archive-2",
            blocking=True,
        )
    assert conflict.value.code == "revision_conflict"


def test_delete_unregisters_and_keeps_directory_by_default(tmp_path, minimal_ics55_pdk_factory):
    project, workspace = _managed_workspace(tmp_path, minimal_ics55_pdk_factory)

    delete_managed_workspace(
        project,
        "baseline",
        1,
        command_id="delete-keep-1",
        delete_directory=False,
        blocking=True,
    )

    assert load_project_manifest(project)["workspaces"] == []
    assert workspace.is_dir()
    commands = json.loads(
        (workspace / "home" / "workspace-commands.json").read_text(encoding="utf-8")
    )
    assert "delete-keep-1" in commands["commands"]


def test_delete_directory_is_limited_to_internal_direct_child(tmp_path, minimal_ics55_pdk_factory):
    project, workspace = _managed_workspace(tmp_path, minimal_ics55_pdk_factory)

    delete_managed_workspace(
        project,
        "baseline",
        1,
        command_id="delete-tree-1",
        delete_directory=True,
        blocking=True,
    )

    assert load_project_manifest(project)["workspaces"] == []
    assert not workspace.exists()
    assert not (project / ".ecc-delete-baseline-delete-tree-1").exists()


def test_lifecycle_refuses_registered_runtime_process(tmp_path, minimal_ics55_pdk_factory):
    project, workspace = _managed_workspace(tmp_path, minimal_ics55_pdk_factory)
    path = project / "project.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["runtime_processes"] = {"baseline": {"run_id": "active"}}
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(WorkspaceLifecycleError) as running:
        archive_managed_workspace(
            project,
            "baseline",
            1,
            command_id="archive-1",
            blocking=True,
        )
    assert running.value.code == "workspace_running"
    assert workspace.is_dir()


def _stage_delete(project: Path, workspace: Path, workspace_id: str, command_id: str) -> Path:
    from chipcompiler.engine.snapshot import read_engineering_snapshot_from_directory
    from chipcompiler.engine.workspace_lifecycle import (
        _workspace_command_fingerprint,
        _write_workspace_command,
    )

    manifest = load_project_manifest(project)
    snapshot = read_engineering_snapshot_from_directory(workspace)
    fingerprint = _workspace_command_fingerprint(
        "delete",
        {
            "project": str(project.resolve()),
            "workspaceId": workspace_id,
            "workspace": str(workspace.resolve()),
            "deleteDirectory": True,
        },
        {},
        snapshot["workspaceRevision"],
    )
    _write_workspace_command(
        workspace,
        command_id,
        fingerprint,
        snapshot["workspaceId"],
        snapshot["workspaceRevision"],
        metadata={
            "operation": "delete",
            "projectId": manifest["project_id"],
            "workspaceId": workspace_id,
            "workspacePath": str(workspace.resolve()),
            "phase": "intent",
        },
    )
    staging = project / f".ecc-delete-{workspace_id}-{command_id}"
    workspace.rename(staging)
    return staging


def test_reconcile_delete_restores_staging_when_manifest_entry_remains(
    tmp_path, minimal_ics55_pdk_factory
):
    project, workspace = _managed_workspace(tmp_path, minimal_ics55_pdk_factory)
    staging = _stage_delete(project, workspace, "baseline", "delete-crash-1")

    recovered = reconcile_workspace_deletes(project, blocking=False)

    assert recovered == ("restored:baseline",)
    assert workspace.is_dir()
    assert not staging.exists()


def test_reconcile_delete_removes_staging_after_manifest_commit(
    tmp_path, minimal_ics55_pdk_factory
):
    project, workspace = _managed_workspace(tmp_path, minimal_ics55_pdk_factory)
    staging = _stage_delete(project, workspace, "baseline", "delete-crash-2")
    mutate_project_manifest(
        project, {"type": "delete_workspace", "workspace_id": "baseline"}
    )

    recovered = reconcile_workspace_deletes(project, blocking=False)

    assert recovered == ("removed:baseline",)
    assert not workspace.exists()
    assert not staging.exists()


def test_reconcile_delete_preserves_unproven_staging(
    tmp_path, minimal_ics55_pdk_factory
):
    project, workspace = _managed_workspace(tmp_path, minimal_ics55_pdk_factory)
    staging = project / ".ecc-delete-baseline-unknown"
    workspace.rename(staging)

    with pytest.raises(WorkspaceLifecycleError) as caught:
        reconcile_workspace_deletes(project, blocking=False)

    assert caught.value.code == "workspace_delete_recovery_unproven"
    assert staging.is_dir()
