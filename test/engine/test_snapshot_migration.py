import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.engine.snapshot import (
    SNAPSHOT_SCHEMA_VERSION,
    SNAPSHOT_V3_SCHEMA_VERSION,
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
        parameters=SimpleNamespace(data={"design": "gcd"}),
        design=SimpleNamespace(name="gcd"),
    )


def _write_legacy_snapshot(workspace, version: int = 2) -> dict:
    current = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")
    legacy = deepcopy(current)
    legacy["schemaVersion"] = version
    legacy.pop("workspaceBindings")
    legacy.pop("stepOutputs")
    legacy["workspaceSpec"] = {"parameters": {}}
    path = Path(workspace.directory) / "home" / "engineering-snapshot.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")
    return legacy


@pytest.mark.parametrize("legacy_version", [2, SNAPSHOT_V3_SCHEMA_VERSION])
def test_migration_preserves_identity_revision_and_projects_v4(tmp_path, legacy_version):
    workspace = _workspace(tmp_path)
    current = _write_legacy_snapshot(workspace, legacy_version)
    assert str(workspace.directory) not in json.dumps(current["qorSnapshotExtension"])

    migrated = migrate_engineering_snapshot(
        workspace,
        expected_workspace_revision=current["workspaceRevision"],
    )

    assert migrated["schemaVersion"] == SNAPSHOT_SCHEMA_VERSION
    assert migrated["workspaceId"] == "engineering-gcd"
    assert migrated["workspaceRevision"] == current["workspaceRevision"]
    assert migrated["cause"] == "snapshot.migrated.to_v4"
    assert migrated["qorSnapshotExtension"]["scoringEngine"] == "qor-v3"
    assert isinstance(migrated["workspaceSpec"], dict)
    assert isinstance(migrated["workspaceBindings"], dict)
    assert isinstance(migrated["stepOutputs"], dict)
    assert read_engineering_snapshot(workspace)["schemaVersion"] == SNAPSHOT_SCHEMA_VERSION


def test_migration_preserves_stale_predecessor_metadata(tmp_path):
    workspace = _workspace(tmp_path)
    current = _write_legacy_snapshot(workspace)
    path = Path(workspace.directory) / "home" / "engineering-snapshot.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["stalePredecessor"] = {"workspaceRevision": 1, "invalidatedStepIds": ["route"]}
    path.write_text(json.dumps(payload), encoding="utf-8")

    migrated = migrate_engineering_snapshot(workspace)

    assert migrated["workspaceRevision"] == current["workspaceRevision"]
    assert migrated["stalePredecessor"] == payload["stalePredecessor"]


def test_migration_failure_keeps_previous_snapshot(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    _write_legacy_snapshot(workspace)
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


def test_production_write_paths_reject_legacy_snapshot(tmp_path):
    workspace = _workspace(tmp_path)
    _write_legacy_snapshot(workspace, SNAPSHOT_V3_SCHEMA_VERSION)

    with pytest.raises(EngineeringSnapshotError, match="requires schemaVersion 4"):
        ensure_engineering_snapshot(workspace)


def test_v4_requires_persisted_gui_projection(tmp_path):
    workspace = _workspace(tmp_path)
    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")
    path = Path(workspace.directory) / "home" / "engineering-snapshot.json"

    for field in ("workspaceSpec", "workspaceBindings", "stepOutputs"):
        invalid = deepcopy(snapshot)
        invalid.pop(field)
        path.write_text(json.dumps(invalid), encoding="utf-8")
        with pytest.raises(EngineeringSnapshotError, match=field):
            read_engineering_snapshot(workspace)


def test_v4_rejects_unauthorized_absolute_step_output(tmp_path):
    workspace = _workspace(tmp_path)
    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")
    path = Path(workspace.directory) / "home" / "engineering-snapshot.json"
    snapshot["stepOutputs"]["sdc"] = {"path": "/etc/passwd", "exists": True}
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    with pytest.raises(EngineeringSnapshotError, match="step output path"):
        read_engineering_snapshot(workspace)


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


@pytest.mark.parametrize("severity", [0, 0.5, 1])
def test_qor_extension_validator_accepts_diagnosis_severity(severity):
    extension = unavailable_qor_snapshot_extension("analysis unavailable")
    extension["status"] = "available"
    extension.pop("reason")
    extension["diagnoses"] = [
        {
            "diagnosisId": "diag.place.congestion",
            "state": "WATCH",
            "severity": severity,
            "confidence": "HIGH",
            "triggerFeatures": ["congestion_severity_index"],
            "affectedDimensions": ["interconnect"],
            "interventions": [],
            "interventionConfidence": "MEDIUM",
            "validationRequired": None,
        }
    ]

    assert validate_qor_snapshot_extension(extension)


@pytest.mark.parametrize("severity", [None, True, -0.01, 1.01])
def test_qor_extension_validator_rejects_invalid_diagnosis_severity(severity):
    extension = unavailable_qor_snapshot_extension("analysis unavailable")
    extension["status"] = "available"
    extension.pop("reason")
    extension["diagnoses"] = [
        {
            "diagnosisId": "diag.place.congestion",
            "state": "WATCH",
            "severity": severity,
            "confidence": "HIGH",
            "triggerFeatures": ["congestion_severity_index"],
            "affectedDimensions": ["interconnect"],
            "interventions": [],
            "interventionConfidence": "MEDIUM",
            "validationRequired": None,
        }
    ]

    assert not validate_qor_snapshot_extension(extension)


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
