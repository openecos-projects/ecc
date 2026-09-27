import json

import pytest

from chipcompiler.data.workspace_transaction import WorkspaceFileTransaction


def test_rollback_restores_files_and_removes_new_managed_files(tmp_path):
    workspace = tmp_path / "workspace"
    home = workspace / "home"
    home.mkdir(parents=True)
    existing = home / "params.toml"
    created = home / "engineering-snapshot.json"
    existing.write_text("before", encoding="utf-8")

    transaction = WorkspaceFileTransaction.begin(workspace, [existing, created])
    existing.write_text("after", encoding="utf-8")
    created.write_text("new", encoding="utf-8")
    transaction.rollback()

    assert existing.read_text(encoding="utf-8") == "before"
    assert not created.exists()
    assert not (home / ".workspace-configuration-backup").exists()


def test_absent_marker_cannot_name_paths_outside_allowlist(tmp_path):
    workspace = tmp_path / "workspace"
    home = workspace / "home"
    home.mkdir(parents=True)
    target = home / "engineering-snapshot.json"
    outside = tmp_path / "outside"
    outside.write_text("keep", encoding="utf-8")

    transaction = WorkspaceFileTransaction.begin(workspace, [target])
    marker = transaction.backup / ".absent-paths.json"
    marker.write_text(
        json.dumps({"schemaVersion": 1, "paths": ["../outside"]}),
        encoding="utf-8",
    )

    with pytest.raises(OSError, match="Invalid Workspace transaction path"):
        transaction.rollback()
    assert outside.read_text(encoding="utf-8") == "keep"


def test_transaction_rejects_caller_paths_outside_fixed_workspace_areas(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "home").mkdir(parents=True)

    with pytest.raises(OSError, match="Invalid Workspace transaction path"):
        WorkspaceFileTransaction.begin(workspace, [workspace / "other" / "file.json"])
