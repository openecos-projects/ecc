import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.engine.snapshot import (
    SNAPSHOT_SCHEMA_VERSION,
    EngineeringSnapshotError,
    commit_engineering_snapshot,
    create_engineering_snapshot,
    ensure_engineering_snapshot,
    invalidate_engineering_snapshot,
    read_engineering_snapshot,
    read_stale_engineering_snapshot,
)

CONTRACT_SECTIONS = {
    "schemaVersion",
    "workspaceId",
    "workspaceRevision",
    "cause",
    "flow",
    "parameters",
    "metrics",
    "qorSnapshotExtension",
    "signoffAssessment",
    "timingPreview",
    "hotspotPreview",
    "checklist",
    "artifacts",
}


def _workspace(tmp_path, steps=None):
    root = tmp_path / "workspace"
    (root / "home").mkdir(parents=True)
    steps = (
        steps if steps is not None else [{"name": "Synthesis", "tool": "yosys", "state": "Success"}]
    )
    return SimpleNamespace(
        directory=root,
        flow=SimpleNamespace(data={"steps": steps}),
        home=SimpleNamespace(data={}),
        parameters=SimpleNamespace(data={"design": "gcd"}),
        design=SimpleNamespace(name="gcd"),
    )


def _snapshot_path(workspace):
    return Path(workspace.directory) / "home" / "engineering-snapshot.json"


def test_create_writes_compact_v6_snapshot_that_round_trips(tmp_path):
    workspace = _workspace(tmp_path)

    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    assert set(snapshot) == CONTRACT_SECTIONS
    assert snapshot["schemaVersion"] == SNAPSHOT_SCHEMA_VERSION
    assert snapshot["workspaceRevision"] == 1
    on_disk = _snapshot_path(workspace).read_text(encoding="utf-8")
    assert "\n" not in on_disk
    assert json.loads(on_disk) == snapshot
    assert read_engineering_snapshot(workspace) == snapshot


def test_artifacts_are_a_pure_index_without_content_fingerprints(tmp_path):
    workspace = _workspace(tmp_path)
    metrics_path = Path(workspace.directory) / "Synthesis_yosys" / "analysis" / "qor_metrics.json"
    metrics_path.parent.mkdir(parents=True)
    metrics_path.write_text('{"schema_version": 3, "metrics": []}', encoding="utf-8")

    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    assert snapshot["artifacts"]
    for artifact in snapshot["artifacts"]:
        assert set(artifact) == {
            "artifactId",
            "kind",
            "name",
            "stepId",
            "reference",
            "availability",
        }
        assert artifact["availability"] in {"missing", "available"}
    indexed = next(
        artifact for artifact in snapshot["artifacts"] if artifact["kind"] == "qor_metrics"
    )
    assert indexed["availability"] == "available"
    assert indexed["reference"] == "Synthesis_yosys/analysis/qor_metrics.json"


def test_read_fails_closed_on_unsupported_schema_version(tmp_path):
    workspace = _workspace(tmp_path)
    create_engineering_snapshot(workspace, workspace_id="engineering-gcd")
    path = _snapshot_path(workspace)
    for version in (2, 3, 99):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["schemaVersion"] = version
        path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(EngineeringSnapshotError, match="snapshot_rebuild_required"):
            read_engineering_snapshot(workspace)


def test_read_validates_expected_identity_and_revision(tmp_path):
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


def test_read_rejects_invalid_sections_and_artifacts(tmp_path):
    workspace = _workspace(tmp_path)
    create_engineering_snapshot(workspace, workspace_id="engineering-gcd")
    path = _snapshot_path(workspace)
    payload = json.loads(path.read_text(encoding="utf-8"))

    invalid_section = {**payload, "flow": []}
    path.write_text(json.dumps(invalid_section), encoding="utf-8")
    with pytest.raises(EngineeringSnapshotError, match="section: flow"):
        read_engineering_snapshot(workspace)

    artifact = {**payload["artifacts"][0], "reference": "/etc/passwd"}
    invalid_artifact = {**payload, "artifacts": [artifact]}
    path.write_text(json.dumps(invalid_artifact), encoding="utf-8")
    with pytest.raises(EngineeringSnapshotError, match="artifact reference"):
        read_engineering_snapshot(workspace)

    path.write_text(json.dumps(payload), encoding="utf-8")
    assert read_engineering_snapshot(workspace)["workspaceId"] == "engineering-gcd"


def test_commit_is_a_full_rebuild_that_advances_revision(tmp_path):
    workspace = _workspace(tmp_path)
    create_engineering_snapshot(workspace, workspace_id="engineering-gcd")
    committed = commit_engineering_snapshot(
        workspace, workspace_id="engineering-gcd", cause="flow_step.success"
    )
    assert committed["workspaceRevision"] == 2
    assert committed["cause"] == "flow_step.success"

    layout = Path(workspace.directory) / "Synthesis_yosys" / "output" / "gcd_Synthesis.png"
    layout.parent.mkdir(parents=True)
    layout.write_bytes(b"layout")
    rebuilt = commit_engineering_snapshot(
        workspace, workspace_id="engineering-gcd", cause="flow_step.success"
    )
    layout_artifact = next(
        artifact for artifact in rebuilt["artifacts"] if artifact["kind"] == "layout_image"
    )
    assert layout_artifact["availability"] == "available"
    assert rebuilt["workspaceRevision"] == 3


def test_commit_rejects_foreign_workspace_identity(tmp_path):
    workspace = _workspace(tmp_path)
    create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    with pytest.raises(EngineeringSnapshotError, match="identity changed"):
        commit_engineering_snapshot(workspace, workspace_id="other", cause="flow_step.success")


def test_invalidate_marks_stale_predecessor_and_commit_clears_it(tmp_path):
    steps = [
        {"name": "Synthesis", "tool": "yosys", "state": "Success"},
        {"name": "Route", "tool": "ecc", "state": "Success"},
    ]
    workspace = _workspace(tmp_path, steps)
    create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    invalidated = invalidate_engineering_snapshot(
        workspace,
        workspace_id="engineering-gcd",
        cause="parameters.updated",
        first_invalidated_step="Route",
    )

    assert invalidated["stalePredecessor"] == {
        "workspaceRevision": 1,
        "invalidatedStepIds": ["Route"],
    }
    states = {step["name"]: step["state"] for step in invalidated["flow"]["steps"]}
    assert states == {"Synthesis": "Success", "Route": "Unstart"}
    stale = read_stale_engineering_snapshot(workspace)
    assert stale is not None
    assert stale["workspaceRevision"] == 1

    workspace.flow.data["steps"][1]["state"] = "Success"
    committed = commit_engineering_snapshot(
        workspace, workspace_id="engineering-gcd", cause="flow_step.success"
    )
    assert "stalePredecessor" not in committed
    assert read_stale_engineering_snapshot(workspace) is None


def test_ensure_creates_missing_snapshot_and_reads_existing(tmp_path):
    workspace = _workspace(tmp_path)

    created = ensure_engineering_snapshot(workspace)
    assert created["cause"] == "workspace.migrated"
    assert read_engineering_snapshot(workspace) == created


def test_ensure_fails_closed_on_dangling_symlink_without_writing_through(tmp_path):
    workspace = _workspace(tmp_path)
    target = tmp_path / "outside.json"
    _snapshot_path(workspace).symlink_to(target)

    with pytest.raises(EngineeringSnapshotError, match="invalid Engineering Snapshot"):
        ensure_engineering_snapshot(workspace)

    assert not target.exists()


def test_read_tolerates_legacy_artifact_fingerprint_fields(tmp_path):
    workspace = _workspace(tmp_path)
    create_engineering_snapshot(workspace, workspace_id="engineering-gcd")
    path = _snapshot_path(workspace)
    payload = json.loads(path.read_text(encoding="utf-8"))
    for artifact in payload["artifacts"]:
        artifact["sha256"] = "0" * 64
        artifact["sizeBytes"] = 123
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert read_engineering_snapshot(workspace) == payload


def test_qor_extension_falls_back_to_unavailable(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)

    def fail(_workspace):
        raise RuntimeError("broken analysis")

    monkeypatch.setattr("chipcompiler.analysis.qor.build_qor_analysis", fail)
    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    assert snapshot["qorSnapshotExtension"]["status"] == "unavailable"
    assert read_engineering_snapshot(workspace) == snapshot
