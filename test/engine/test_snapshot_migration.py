import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.engine.snapshot import (
    EngineeringSnapshotError,
    create_engineering_snapshot,
    ensure_engineering_snapshot,
    migrate_engineering_snapshot,
    read_engineering_snapshot,
)
from chipcompiler.engine.snapshot_qor import (
    unavailable_qor_snapshot_extension,
    validate_qor_snapshot_extension,
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


def test_new_snapshot_uses_schema_five_and_projects_v3_qor(tmp_path):
    workspace = _workspace(tmp_path)
    current = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")
    assert current["schemaVersion"] == 5
    assert str(workspace.directory) not in json.dumps(current["qorSnapshotExtension"])
    assert "qorAssessment" not in current
    assert read_engineering_snapshot(workspace)["schemaVersion"] == 5


def test_legacy_migration_requires_explicit_rebuild(tmp_path):
    workspace = _workspace(tmp_path)
    create_engineering_snapshot(workspace, workspace_id="engineering-gcd")
    with pytest.raises(EngineeringSnapshotError, match="rebuild the workspace"):
        migrate_engineering_snapshot(workspace)


def test_unsupported_schema_is_not_migrated(tmp_path):
    workspace = _workspace(tmp_path)
    path = Path(workspace.directory) / "home" / "engineering-snapshot.json"
    path.write_text(json.dumps({"schemaVersion": 99}), encoding="utf-8")

    with pytest.raises(EngineeringSnapshotError, match="rebuild the workspace"):
        migrate_engineering_snapshot(workspace)


def test_qor_extension_validator_rejects_missing_and_invalid_nested_fields():
    extension = unavailable_qor_snapshot_extension("analysis unavailable")
    assert validate_qor_snapshot_extension(extension)

    missing_score = deepcopy(extension)
    missing_score.pop("score")
    assert not validate_qor_snapshot_extension(missing_score)

    invalid_power = deepcopy(extension)
    invalid_power["power"]["sourceKind"] = "raw_file"
    assert not validate_qor_snapshot_extension(invalid_power)

    invalid_gate = deepcopy(extension)
    invalid_gate["feasibility"]["gates"].append({"id": "broken"})
    assert not validate_qor_snapshot_extension(invalid_gate)


def test_snapshot_read_validates_expected_identity_and_revision(tmp_path):
    workspace = _workspace(tmp_path)
    create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    with pytest.raises(EngineeringSnapshotError, match="identity mismatch"):
        read_engineering_snapshot(workspace, expected_workspace_id="other")
    with pytest.raises(EngineeringSnapshotError, match="Revision mismatch"):
        read_engineering_snapshot(workspace, expected_workspace_revision=2)

    (workspace.directory / "home" / "workspace-commands.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "commands": {
                    "create-1": {"result": {"workspaceId": "other"}},
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(EngineeringSnapshotError, match="identity mismatch"):
        read_engineering_snapshot(workspace)


def test_snapshot_read_rejects_invalid_sections_and_only_checks_artifacts_when_requested(
    tmp_path,
):
    workspace = _workspace(tmp_path)
    create_engineering_snapshot(workspace, workspace_id="engineering-gcd")
    path = Path(workspace.directory) / "home" / "engineering-snapshot.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    invalid_section = deepcopy(payload)
    invalid_section["flow"] = []
    path.write_text(json.dumps(invalid_section), encoding="utf-8")
    with pytest.raises(EngineeringSnapshotError, match="section: flow"):
        read_engineering_snapshot(workspace)

    path.write_text(json.dumps(payload), encoding="utf-8")
    artifact = payload["artifacts"][0]
    artifact_path = workspace.directory / artifact["reference"]
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_bytes(b"before")
    artifact.update(
        {
            "availability": "available",
            "integrity": "verified",
            "sizeBytes": 6,
            "sha256": hashlib.sha256(b"before").hexdigest(),
        }
    )
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert read_engineering_snapshot(workspace)["artifacts"][0]["availability"] == "available"

    artifact_path.write_bytes(b"after")
    assert read_engineering_snapshot(workspace)["artifacts"][0]["availability"] == "available"
    assert ensure_engineering_snapshot(workspace)["workspaceId"] == "engineering-gcd"
    with pytest.raises(
        EngineeringSnapshotError,
        match=f"fingerprint mismatch: {artifact['reference']}",
    ):
        read_engineering_snapshot(workspace, validate_artifacts=True)
