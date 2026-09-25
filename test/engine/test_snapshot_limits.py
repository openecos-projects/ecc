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


def test_snapshot_indexes_step_subflow_artifact(tmp_path):
    workspace = _sta_workspace(tmp_path)
    root = Path(workspace.directory)
    step_dir = root / "sta_ecc"
    step_dir.mkdir(parents=True)
    (step_dir / "subflow.json").write_text(
        json.dumps(
            {
                "path": str(step_dir / "subflow.json"),
                "steps": [
                    {
                        "name": "run sta",
                        "state": "Success",
                        "runtime": "0:00:01",
                        "peak memory (mb)": 12.5,
                        "info": "",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    subflow_artifacts = [
        artifact for artifact in snapshot["artifacts"] if artifact["kind"] == "subflow"
    ]
    assert [artifact["reference"] for artifact in subflow_artifacts] == ["sta_ecc/subflow.json"]
    assert subflow_artifacts[0]["stepId"] == "sta"
    assert subflow_artifacts[0]["availability"] == "available"


def test_snapshot_indexes_lec_reports_and_rcx_feature_facts(tmp_path):
    root = tmp_path / "workspace"
    (root / "home").mkdir(parents=True)
    workspace = SimpleNamespace(
        directory=root,
        flow=SimpleNamespace(
            data={
                "steps": [
                    {"name": "postRouteLec", "tool": "yosys_lec", "state": "Success"},
                    {"name": "RCX", "tool": "ecc", "state": "Success"},
                ]
            }
        ),
        home=SimpleNamespace(data={}),
        parameters=SimpleNamespace(data={"design": "gcd"}),
        design=SimpleNamespace(name="gcd"),
    )
    lec_report = root / "postRouteLec_yosys_lec" / "report"
    lec_report.mkdir(parents=True)
    (lec_report / "run_lec_status.rpt").write_text("status", encoding="utf-8")
    (lec_report / "equiv_status.rpt").write_text("equiv", encoding="utf-8")
    rcx_feature = root / "RCX_ecc" / "feature"
    rcx_feature.mkdir(parents=True)
    (rcx_feature / "RCX.step.json").write_text('{"rcx": {}}', encoding="utf-8")

    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    lec_reports = [
        artifact["reference"]
        for artifact in snapshot["artifacts"]
        if artifact["kind"] == "report_text" and artifact["stepId"] == "postRouteLec"
    ]
    assert lec_reports == [
        "postRouteLec_yosys_lec/report/run_lec_status.rpt",
        "postRouteLec_yosys_lec/report/equiv_status.rpt",
    ]
    rcx_facts = [
        artifact
        for artifact in snapshot["artifacts"]
        if artifact["kind"] == "rcx_feature_facts"
    ]
    assert [artifact["reference"] for artifact in rcx_facts] == ["RCX_ecc/feature/RCX.step.json"]
    assert rcx_facts[0]["availability"] == "available"


def test_snapshot_indexes_power_analysis_artifacts(tmp_path):
    root = tmp_path / "workspace"
    (root / "home").mkdir(parents=True)
    report = root / "powerAnalysis_ecc" / "data" / "pw" / "power_reporter" / "power.rpt"
    report.parent.mkdir(parents=True)
    report.write_text("Total Dynamic Power = 1.0 mW\n", encoding="utf-8")
    summary = root / "powerAnalysis_ecc" / "feature" / "power_summary.json"
    summary.parent.mkdir(parents=True)
    summary.write_text('{"schema_version": 1}\n', encoding="utf-8")
    workspace = SimpleNamespace(
        directory=root,
        flow=SimpleNamespace(
            data={"steps": [{"name": "powerAnalysis", "tool": "ecc", "state": "Success"}]}
        ),
        parameters=SimpleNamespace(data={"design": "gcd"}),
        design=SimpleNamespace(name="gcd"),
    )

    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    power_artifacts = [
        artifact
        for artifact in snapshot["artifacts"]
        if artifact["kind"] in {"power_report", "power_summary"}
    ]
    assert [(artifact["kind"], artifact["reference"]) for artifact in power_artifacts] == [
        ("power_report", "powerAnalysis_ecc/data/pw/power_reporter/power.rpt"),
        ("power_summary", "powerAnalysis_ecc/feature/power_summary.json"),
    ]
    assert all(artifact["availability"] == "available" for artifact in power_artifacts)


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
