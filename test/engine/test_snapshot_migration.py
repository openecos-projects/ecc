import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.engine.snapshot import (
    SNAPSHOT_V3_SCHEMA_VERSION,
    EngineeringSnapshotError,
    create_engineering_snapshot,
    migrate_engineering_snapshot,
    read_engineering_snapshot,
)


def _workspace(tmp_path):
    root = tmp_path / "workspace"
    (root / "home").mkdir(parents=True)
    steps = [{"name": "Synthesis", "tool": "yosys", "state": "Success"}]
    (root / "home" / "flow.json").write_text(json.dumps({"steps": steps}), encoding="utf-8")
    return SimpleNamespace(
        directory=root,
        flow=SimpleNamespace(data={"steps": steps}),
        home=SimpleNamespace(data={}),
        parameters=SimpleNamespace(data={"design": "gcd"}),
        design=SimpleNamespace(name="gcd"),
    )


def test_migration_preserves_identity_advances_revision_and_projects_qor(tmp_path):
    workspace = _workspace(tmp_path)
    current = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    migrated = migrate_engineering_snapshot(
        workspace,
        expected_workspace_revision=current["workspaceRevision"],
    )

    assert migrated["schemaVersion"] == SNAPSHOT_V3_SCHEMA_VERSION
    assert migrated["workspaceId"] == "engineering-gcd"
    assert migrated["workspaceRevision"] == current["workspaceRevision"] + 1
    assert migrated["cause"] == "snapshot.migrated.v2_to_v3"
    assert migrated["qorSnapshotExtension"]["scoringEngine"] == "qor-v3"
    assert read_engineering_snapshot(workspace)["schemaVersion"] == SNAPSHOT_V3_SCHEMA_VERSION


def test_migration_preserves_stale_predecessor_metadata(tmp_path):
    workspace = _workspace(tmp_path)
    current = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")
    path = Path(workspace.directory) / "home" / "engineering-snapshot.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["stalePredecessor"] = {"workspaceRevision": 1, "invalidatedStepIds": ["route"]}
    path.write_text(json.dumps(payload), encoding="utf-8")

    migrated = migrate_engineering_snapshot(workspace)

    assert migrated["workspaceRevision"] == current["workspaceRevision"] + 1
    assert migrated["stalePredecessor"] == payload["stalePredecessor"]


def test_migration_failure_keeps_previous_snapshot(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    create_engineering_snapshot(workspace, workspace_id="engineering-gcd")
    path = Path(workspace.directory) / "home" / "engineering-snapshot.json"
    before = path.read_bytes()

    def fail(_workspace):
        raise RuntimeError("broken analysis")

    monkeypatch.setattr("chipcompiler.analysis.qor.build_qor_analysis", fail)
    with pytest.raises(EngineeringSnapshotError, match="regenerate QoR facts"):
        migrate_engineering_snapshot(workspace)

    assert path.read_bytes() == before


def test_unsupported_schema_is_not_migrated(tmp_path):
    workspace = _workspace(tmp_path)
    path = Path(workspace.directory) / "home" / "engineering-snapshot.json"
    path.write_text(json.dumps({"schemaVersion": 99}), encoding="utf-8")

    with pytest.raises(EngineeringSnapshotError, match="invalid Engineering Snapshot"):
        migrate_engineering_snapshot(workspace)
