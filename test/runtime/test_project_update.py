#!/usr/bin/env python

"""RPC in-place workspace update refreshes the owning project manifest."""

import json
from copy import deepcopy
from pathlib import Path

from chipcompiler.project import (
    create_project_manifest,
    load_project_manifest,
    mutate_project_manifest,
)
from chipcompiler.runtime.requests import WorkspaceSpecCreateRequest, WorkspaceUpdateRequest
from chipcompiler.runtime.workspace_api import WorkspaceRuntimeApi


def _spec_fixture(name: str):
    root = Path(__file__).parents[1] / "fixtures" / "workspace_spec"
    payload = json.loads((root / name).read_text(encoding="utf-8"))
    bindings = deepcopy(payload["workspaceBindings"])
    bindings["inputs"] = {key: str(root / value) for key, value in bindings["inputs"].items()}
    return payload, bindings


def test_update_workspace_refreshes_project_manifest_derived_fields(
    tmp_path, minimal_ics55_pdk_factory
):
    project_dir = tmp_path / "proj"
    create_project_manifest(project_dir, "Demo", "gcd", now="2026-01-01T00:00:00Z")
    payload, bindings = _spec_fixture("valid.json")
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    api = WorkspaceRuntimeApi()
    created = api.create_workspace(
        WorkspaceSpecCreateRequest(
            command_id="create-1",
            target_directory=str(project_dir / "experiment"),
            workspace_spec=payload["workspaceSpec"],
            workspace_bindings=bindings,
            project_root=str(project_dir),
        )
    )
    (entry,) = load_project_manifest(project_dir)["workspaces"]
    assert entry["parameter_patch"] == {}

    updated_spec = deepcopy(payload["workspaceSpec"])
    updated_spec["parameters"]["design.frequency_mhz"] = 250.0
    updated = api.update_workspace(
        WorkspaceUpdateRequest(
            command_id="update-1",
            workspace_id=created["workspaceId"],
            expected_workspace_revision=created["workspaceRevision"],
            workspace_spec=updated_spec,
            workspace_bindings=bindings,
        )
    )

    assert updated["workspaceRevision"] == created["workspaceRevision"] + 1
    assert updated["backupDirectory"] is None
    (entry,) = load_project_manifest(project_dir)["workspaces"]
    # The entry re-converged on the updated directory without GUI involvement:
    # a new-generation (never-run) workspace derives not_started.
    assert entry["status"] == "not_started"
    assert entry["start_step"] == "Synth"
    assert entry["end_step"] == "Harden"
    assert entry["parameter_patch"]["frequency_max"] == {"from": None, "to": 250.0}


def test_update_workspace_retain_backup_registers_archived_backup_entry(
    tmp_path, minimal_ics55_pdk_factory
):
    project_dir = tmp_path / "proj"
    create_project_manifest(project_dir, "Demo", "gcd", now="2026-01-01T00:00:00Z")
    payload, bindings = _spec_fixture("valid.json")
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    api = WorkspaceRuntimeApi()
    created = api.create_workspace(
        WorkspaceSpecCreateRequest(
            command_id="create-1",
            target_directory=str(project_dir / "experiment"),
            workspace_spec=payload["workspaceSpec"],
            workspace_bindings=bindings,
            project_root=str(project_dir),
        )
    )
    updated_spec = deepcopy(payload["workspaceSpec"])
    updated_spec["parameters"]["design.frequency_mhz"] = 250.0

    updated = api.update_workspace(
        WorkspaceUpdateRequest(
            command_id="update-1",
            workspace_id=created["workspaceId"],
            expected_workspace_revision=created["workspaceRevision"],
            workspace_spec=updated_spec,
            workspace_bindings=bindings,
            retain_backup=True,
        )
    )

    backup = project_dir / ".experiment.replace-backup-1"
    assert updated["workspaceRevision"] == created["workspaceRevision"] + 1
    assert updated["backupDirectory"] == str(backup)
    assert backup.is_dir()
    # The backup holds the replaced generation's snapshot, same lineage.
    from chipcompiler.engine.snapshot import read_engineering_snapshot_from_directory

    retained = read_engineering_snapshot_from_directory(backup)
    assert retained["workspaceId"] == created["workspaceId"]
    assert retained["workspaceRevision"] == created["workspaceRevision"]

    workspaces = load_project_manifest(project_dir)["workspaces"]
    assert len(workspaces) == 2
    (backup_entry,) = [w for w in workspaces if w["workspace_id"] == backup.name]
    assert backup_entry["workspace_path"] == str(backup)
    assert backup_entry["status"] == "archived"
    assert backup_entry["source_workspace_id"] == "experiment"
    # The archived entry's range is derived from the backup's own flow.json.
    assert backup_entry["start_step"] == "Synth"
    assert backup_entry["end_step"] == "Harden"
    (entry,) = [w for w in workspaces if w["workspace_id"] == "experiment"]
    assert entry["status"] == "not_started"


def test_update_workspace_retain_backup_without_project_skips_registration(
    tmp_path, minimal_ics55_pdk_factory, caplog
):
    payload, bindings = _spec_fixture("valid.json")
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    api = WorkspaceRuntimeApi()
    created = api.create_workspace(
        WorkspaceSpecCreateRequest(
            command_id="create-1",
            target_directory=str(tmp_path / "workspace"),
            workspace_spec=payload["workspaceSpec"],
            workspace_bindings=bindings,
        )
    )
    updated_spec = deepcopy(payload["workspaceSpec"])

    with caplog.at_level("WARNING", logger="chipcompiler.runtime.manifest_status"):
        updated = api.update_workspace(
            WorkspaceUpdateRequest(
                command_id="update-1",
                workspace_id=created["workspaceId"],
                expected_workspace_revision=created["workspaceRevision"],
                workspace_spec=updated_spec,
                workspace_bindings=bindings,
                retain_backup=True,
            )
        )

    backup = tmp_path / ".workspace.replace-backup-1"
    assert updated["backupDirectory"] == str(backup)
    assert backup.is_dir()
    assert not (tmp_path / "project.json").exists()
    assert "no owning project" in caplog.text


def test_update_workspace_repoints_baseline_and_best_to_retained_backup(
    tmp_path, minimal_ics55_pdk_factory
):
    project_dir = tmp_path / "proj"
    create_project_manifest(project_dir, "Demo", "gcd", now="2026-01-01T00:00:00Z")
    payload, bindings = _spec_fixture("valid.json")
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    api = WorkspaceRuntimeApi()
    created = api.create_workspace(
        WorkspaceSpecCreateRequest(
            command_id="create-1",
            target_directory=str(project_dir / "experiment"),
            workspace_spec=payload["workspaceSpec"],
            workspace_bindings=bindings,
            project_root=str(project_dir),
        )
    )
    mutate_project_manifest(
        project_dir,
        {"type": "select_qor_baseline", "workspace_id": "experiment", "reason": "Pinned"},
    )
    mutate_project_manifest(
        project_dir,
        {"type": "select_best_workspace", "workspace_id": "experiment", "reason": "Best"},
    )
    updated_spec = deepcopy(payload["workspaceSpec"])
    updated_spec["parameters"]["design.frequency_mhz"] = 250.0

    updated = api.update_workspace(
        WorkspaceUpdateRequest(
            command_id="update-1",
            workspace_id=created["workspaceId"],
            expected_workspace_revision=created["workspaceRevision"],
            workspace_spec=updated_spec,
            workspace_bindings=bindings,
            retain_backup=True,
        )
    )

    backup = project_dir / ".experiment.replace-backup-1"
    assert updated["backupDirectory"] == str(backup)
    manifest = load_project_manifest(project_dir)
    # Both pointers followed the archived backup entry holding the replaced
    # generation's artifacts, keeping their recorded reasons.
    assert manifest["qor_baseline"] == {"workspace_id": backup.name, "reason": "Pinned"}
    assert manifest["best_workspace"] == {"workspace_id": backup.name, "reason": "Best"}


def test_update_workspace_without_backup_clears_pointers_at_replaced_workspace(
    tmp_path, minimal_ics55_pdk_factory
):
    project_dir = tmp_path / "proj"
    create_project_manifest(project_dir, "Demo", "gcd", now="2026-01-01T00:00:00Z")
    payload, bindings = _spec_fixture("valid.json")
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    api = WorkspaceRuntimeApi()
    created = api.create_workspace(
        WorkspaceSpecCreateRequest(
            command_id="create-1",
            target_directory=str(project_dir / "experiment"),
            workspace_spec=payload["workspaceSpec"],
            workspace_bindings=bindings,
            project_root=str(project_dir),
        )
    )
    api.create_workspace(
        WorkspaceSpecCreateRequest(
            command_id="create-2",
            target_directory=str(project_dir / "other"),
            workspace_spec=payload["workspaceSpec"],
            workspace_bindings=bindings,
            project_root=str(project_dir),
        )
    )
    mutate_project_manifest(
        project_dir,
        {"type": "select_qor_baseline", "workspace_id": "experiment", "reason": "Pinned"},
    )
    mutate_project_manifest(
        project_dir,
        {"type": "select_best_workspace", "workspace_id": "other", "reason": "Best"},
    )
    updated_spec = deepcopy(payload["workspaceSpec"])

    updated = api.update_workspace(
        WorkspaceUpdateRequest(
            command_id="update-1",
            workspace_id=created["workspaceId"],
            expected_workspace_revision=created["workspaceRevision"],
            workspace_spec=updated_spec,
            workspace_bindings=bindings,
        )
    )

    assert updated["backupDirectory"] is None
    manifest = load_project_manifest(project_dir)
    # No retained backup entry: the baseline cleared (default resolution
    # applies); the pointer at the unrelated workspace is untouched.
    assert manifest["qor_baseline"] is None
    assert manifest["best_workspace"] == {"workspace_id": "other", "reason": "Best"}
