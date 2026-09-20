import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.engine.analysis import _analysis_file, _lec_result_file
from chipcompiler.engine.snapshot import (
    EngineeringSnapshotError,
    _write_snapshot,
    create_engineering_snapshot,
)
from chipcompiler.engine.snapshot_limits import (
    ANALYSIS_FILE_INLINE_MAX_BYTES,
    ENGINEERING_SNAPSHOT_MAX_BYTES,
    InlineJsonBudget,
)


def _write_large_json(path: Path, schema_version: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": schema_version,
                "issues": ["x" * ANALYSIS_FILE_INLINE_MAX_BYTES],
            }
        ),
        encoding="utf-8",
    )


def test_analysis_file_excludes_oversized_payload(tmp_path):
    path = tmp_path / "analysis.json"
    _write_large_json(path)

    result = _analysis_file(path, "artifact-analysis", 1, tmp_path)

    assert result == {
        "artifactId": "artifact-analysis",
        "status": "oversized",
        "reasonCode": "ANALYSIS_FILE_OVERSIZED",
        "data": None,
    }


def test_analysis_file_limits_embedded_size_for_minified_json(tmp_path):
    path = tmp_path / "analysis.json"
    path.write_text(
        json.dumps(
            {"schema_version": 1, "issues": [""] * 40_000},
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    assert path.stat().st_size < ANALYSIS_FILE_INLINE_MAX_BYTES

    result = _analysis_file(path, "artifact-analysis", 1, tmp_path)

    assert result["status"] == "oversized"
    assert result["data"] is None


def test_analysis_file_respects_shared_inline_budget(tmp_path):
    path = tmp_path / "analysis.json"
    path.write_text('{"schema_version": 1, "issues": []}', encoding="utf-8")

    result = _analysis_file(
        path,
        "artifact-analysis",
        1,
        tmp_path,
        InlineJsonBudget(1),
    )

    assert result == {
        "artifactId": "artifact-analysis",
        "status": "oversized",
        "reasonCode": "ANALYSIS_INLINE_BUDGET_EXCEEDED",
        "data": None,
    }


def test_lec_result_excludes_oversized_payload(tmp_path):
    path = tmp_path / "result.json"
    _write_large_json(path)

    result = _lec_result_file(path, "artifact-lec", tmp_path)

    assert result == {
        "artifactId": "artifact-lec",
        "status": "oversized",
        "reasonCode": "LEC_RESULT_OVERSIZED",
        "data": None,
    }


def test_snapshot_keeps_oversized_sta_as_artifact_reference(tmp_path):
    root = tmp_path / "workspace"
    (root / "home").mkdir(parents=True)
    timing_path = root / "sta_ecc" / "analysis" / "sta_timing_issues.json"
    _write_large_json(timing_path)
    steps = [{"name": "sta", "tool": "ecc", "state": "Success"}]
    workspace = SimpleNamespace(
        directory=root,
        flow=SimpleNamespace(data={"steps": steps}),
        home=SimpleNamespace(data={}),
        parameters=SimpleNamespace(data={"design": "gcd"}),
        design=SimpleNamespace(name="gcd"),
    )

    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    assert snapshot["analysis"]["steps"][0]["timingIssues"] == {
        "artifactId": snapshot["analysis"]["steps"][0]["timingIssues"]["artifactId"],
        "status": "oversized",
        "reasonCode": "ANALYSIS_FILE_OVERSIZED",
        "data": None,
    }
    artifact = next(item for item in snapshot["artifacts"] if item["kind"] == "sta_timing_issues")
    assert artifact["reference"] == "sta_ecc/analysis/sta_timing_issues.json"
    assert artifact["sizeBytes"] == timing_path.stat().st_size
    assert (root / "home" / "engineering-snapshot.json").stat().st_size < (
        ENGINEERING_SNAPSHOT_MAX_BYTES
    )


def test_snapshot_indexes_sta_corner_artifacts_when_aggregate_is_oversized(tmp_path):
    root = tmp_path / "workspace"
    (root / "home").mkdir(parents=True)
    _write_large_json(root / "sta_ecc" / "analysis" / "sta_timing_issues.json")
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
    workspace = SimpleNamespace(
        directory=root,
        flow=SimpleNamespace(data={"steps": [{"name": "sta", "tool": "ecc", "state": "Success"}]}),
        home=SimpleNamespace(data={}),
        parameters=SimpleNamespace(data={"design": "gcd"}),
        design=SimpleNamespace(name="gcd"),
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
    assert all(len(artifact["sha256"]) == 64 for artifact in timing_artifacts)


def test_snapshot_limits_sta_corner_artifacts_deterministically(tmp_path):
    root = tmp_path / "workspace"
    (root / "home").mkdir(parents=True)
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
    workspace = SimpleNamespace(
        directory=root,
        flow=SimpleNamespace(data={"steps": [{"name": "sta", "tool": "ecc"}]}),
        home=SimpleNamespace(data={}),
        parameters=SimpleNamespace(data={"design": "gcd"}),
        design=SimpleNamespace(name="gcd"),
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
