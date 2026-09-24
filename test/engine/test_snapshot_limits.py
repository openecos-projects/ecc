import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.engine.snapshot import (
    EngineeringSnapshotError,
    _write_snapshot,
    create_engineering_snapshot,
    read_engineering_snapshot,
)
from chipcompiler.engine.snapshot_limits import ENGINEERING_SNAPSHOT_MAX_BYTES


def _sta_workspace(tmp_path):
    root = tmp_path / "workspace"
    (root / "home").mkdir(parents=True)
    return SimpleNamespace(
        directory=root,
        flow=SimpleNamespace(data={"steps": [{"name": "sta", "tool": "ecc", "state": "Success"}]}),
        home=SimpleNamespace(data={}),
        parameters=SimpleNamespace(data={"design": "gcd"}),
        design=SimpleNamespace(name="gcd"),
    )


def test_snapshot_indexes_sta_corner_artifacts(tmp_path):
    workspace = _sta_workspace(tmp_path)
    root = Path(workspace.directory)
    feature = root / "sta_ecc" / "feature" / "MAX_125" / "RCworst"
    feature.mkdir(parents=True)
    (feature / "qor_summary.json").write_text(
        '{"schema_version":1,"corner":"MAX_125/RCworst","summary":{}}',
        encoding="utf-8",
    )
    (feature / "timing_paths.json").write_text(
        '{"schema_version":1,"corner":"MAX_125/RCworst","path_limit":0,"paths":[]}',
        encoding="utf-8",
    )

    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    timing_artifacts = [
        artifact
        for artifact in snapshot["artifacts"]
        if artifact["kind"] in {"timing_summary", "timing_paths"}
    ]
    assert [artifact["reference"] for artifact in timing_artifacts] == [
        "sta_ecc/feature/MAX_125/RCworst/qor_summary.json",
        "sta_ecc/feature/MAX_125/RCworst/timing_paths.json",
    ]
    assert [artifact["name"] for artifact in timing_artifacts] == [
        "MAX_125/RCworst/qor_summary.json",
        "MAX_125/RCworst/timing_paths.json",
    ]
    assert all(artifact["availability"] == "available" for artifact in timing_artifacts)


def test_snapshot_limits_sta_corner_artifacts_deterministically(tmp_path):
    workspace = _sta_workspace(tmp_path)
    root = Path(workspace.directory)
    for index in range(33):
        feature = root / "sta_ecc" / "feature" / f"P{index:02d}" / "RC"
        feature.mkdir(parents=True)
        (feature / "timing_paths.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "corner": f"P{index:02d}/RC",
                    "path_limit": 0,
                    "paths": [],
                }
            ),
            encoding="utf-8",
        )

    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    timing_paths = [
        artifact for artifact in snapshot["artifacts"] if artifact["kind"] == "timing_paths"
    ]
    assert len(timing_paths) == 32
    assert timing_paths[0]["name"] == "P00/RC/timing_paths.json"
    assert timing_paths[-1]["name"] == "P31/RC/timing_paths.json"


def test_snapshot_size_guard_preserves_existing_file(tmp_path):
    path = tmp_path / "engineering-snapshot.json"
    path.write_text("previous", encoding="utf-8")

    with pytest.raises(EngineeringSnapshotError, match="Engineering Snapshot exceeds"):
        _write_snapshot(path, {"payload": "x" * ENGINEERING_SNAPSHOT_MAX_BYTES})

    assert path.read_text(encoding="utf-8") == "previous"


def test_checklist_projection_cap_is_a_producer_error(tmp_path):
    root = tmp_path / "workspace"
    (root / "home").mkdir(parents=True)
    items = [
        {"id": f"item-{index}", "title": f"Item {index}", "state": "pass"} for index in range(513)
    ]
    (root / "home" / "checklist.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "kind": "signoff_checklist",
                "status": "ready",
                "checklist": items,
            }
        ),
        encoding="utf-8",
    )
    workspace = SimpleNamespace(
        directory=root,
        flow=SimpleNamespace(data={"steps": []}),
        home=SimpleNamespace(data={}),
        parameters=SimpleNamespace(data={"design": "gcd"}),
        design=SimpleNamespace(name="gcd"),
    )

    with pytest.raises(EngineeringSnapshotError, match="512 items"):
        create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    assert not (root / "home" / "engineering-snapshot.json").exists()


def test_artifact_index_cap_is_a_producer_error(tmp_path):
    root = tmp_path / "workspace"
    (root / "home").mkdir(parents=True)
    # 7 indexed artifacts per step (3 analysis files, layout image, geometry
    # manifest, 2 reports): 586 steps overshoot the 4096-entry index limit.
    steps = [
        {"name": f"Step{index:04d}", "tool": "ecc", "state": "Unstart"} for index in range(586)
    ]
    workspace = SimpleNamespace(
        directory=root,
        flow=SimpleNamespace(data={"steps": steps}),
        home=SimpleNamespace(data={}),
        parameters=SimpleNamespace(data={"design": "gcd"}),
        design=SimpleNamespace(name="gcd"),
    )

    with pytest.raises(EngineeringSnapshotError, match="4096 entries"):
        create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    assert not (root / "home" / "engineering-snapshot.json").exists()


def test_read_rejects_artifact_index_beyond_limit(tmp_path):
    workspace = _sta_workspace(tmp_path)
    create_engineering_snapshot(workspace, workspace_id="engineering-gcd")
    path = Path(workspace.directory) / "home" / "engineering-snapshot.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["artifacts"] = payload["artifacts"] * 600
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(EngineeringSnapshotError, match="section: artifacts"):
        read_engineering_snapshot(workspace)
