import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.engine.snapshot import create_engineering_snapshot


def _metric_record(**overrides):
    record = {
        "id": "die_area",
        "display_name": "Die Area",
        "value": 1500.0,
        "category": "area_cost",
        "direction": "lower_is_better",
        "scope": "workspace",
        "corner": None,
        "analysis_group": "harden_metrics",
        "rating": {"gate": False, "score": True, "trend": False},
        "project_role": "final",
        "step_role": "primary",
        "confidence": "high",
        "source": {},
    }
    record.update(overrides)
    return record


def _timing_issue(slack, corner="MAX_125/RCworst", path_id="path-1", **overrides):
    issue = {
        "issue_id": f"sta_timing:{corner}:setup:{path_id}",
        "severity": "critical" if slack < 0 else "warning",
        "corner": corner,
        "analysis_type": "setup",
        "path_group": "clk",
        "start_point": "a/Q",
        "end_point": "b/D",
        "launch_clock": "clk",
        "capture_clock": "clk",
        "check_type": "setup",
        "slack_ns": slack,
        "arrival_ns": 1.0,
        "required_ns": 0.5,
        "cppr_ns": 0.0,
        "launch_clock_network_delay_ns": 0.1,
        "capture_clock_network_delay_ns": 0.1,
        "clock_network_delay_delta_ns": 0.0,
        "source_file": "feature/MAX_125/RCworst/timing_paths.json",
        "dominant_stages": [{"pin": "a/Q", "incremental_delay_ns": 0.4}],
    }
    issue.update(overrides)
    return issue


def _workspace(tmp_path, steps):
    root = tmp_path / "workspace"
    (root / "home").mkdir(parents=True)
    return SimpleNamespace(
        directory=root,
        flow=SimpleNamespace(data={"steps": steps}),
        home=SimpleNamespace(data={}),
        parameters=SimpleNamespace(data={"design": "gcd"}),
        design=SimpleNamespace(name="gcd"),
    )


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_metrics_are_one_flat_validated_list_from_success_steps(tmp_path):
    valid = _metric_record()
    workspace = _workspace(
        tmp_path,
        [
            {"name": "Synthesis", "tool": "yosys", "state": "Success"},
            {"name": "Route", "tool": "ecc", "state": "Ongoing"},
        ],
    )
    root = Path(workspace.directory)
    _write_json(
        root / "Synthesis_yosys" / "analysis" / "qor_metrics.json",
        {"schema_version": 3, "metrics": [valid, _metric_record(value=float("nan"))]},
    )
    _write_json(
        root / "Route_ecc" / "analysis" / "qor_metrics.json",
        {"schema_version": 3, "metrics": [_metric_record(id="route_overflow")]},
    )

    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    assert snapshot["metrics"] == [valid]


def test_metrics_projection_maps_legacy_power_category(tmp_path):
    workspace = _workspace(tmp_path, [{"name": "Synthesis", "tool": "yosys", "state": "Success"}])
    record = _metric_record(
        id="synthesis_power_dynamic_uw",
        category="power",
        direction="trend_only",
    )
    _write_json(
        Path(workspace.directory) / "Synthesis_yosys" / "analysis" / "qor_metrics.json",
        {"schema_version": 3, "metrics": [record]},
    )

    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    assert [metric["category"] for metric in snapshot["metrics"]] == ["power_integrity"]


def test_timing_preview_is_worst_slack_top5_scalars_with_truncation_truth(tmp_path):
    workspace = _workspace(tmp_path, [{"name": "sta", "tool": "ecc", "state": "Success"}])
    issues = [
        _timing_issue(slack, path_id=f"path-{index}")
        for index, slack in enumerate([0.01, -0.05, -0.2, -0.01, -0.3, -0.02, -0.4])
    ]
    _write_json(
        Path(workspace.directory) / "sta_ecc" / "analysis" / "sta_timing_issues.json",
        {"schema_version": 1, "issues": issues},
    )

    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    preview = snapshot["timingPreview"]
    assert preview["issueCount"] == 7
    assert preview["issuesTruncated"] is True
    assert [issue["slack_ns"] for issue in preview["issues"]] == [-0.4, -0.3, -0.2, -0.05, -0.02]
    for issue in preview["issues"]:
        assert "dominant_stages" not in issue
        assert all(
            value is None or isinstance(value, (str, int, float, bool)) for value in issue.values()
        )


def test_timing_preview_is_empty_for_missing_invalid_or_stale_step(tmp_path):
    workspace = _workspace(tmp_path, [{"name": "sta", "tool": "ecc", "state": "Success"}])

    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")
    assert snapshot["timingPreview"] == {"issues": [], "issueCount": 0, "issuesTruncated": False}

    _write_json(
        Path(workspace.directory) / "sta_ecc" / "analysis" / "sta_timing_issues.json",
        {"schema_version": 1, "issues": [_timing_issue(-0.1)]},
    )
    workspace.flow.data["steps"][0]["state"] = "Failed"
    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")
    assert snapshot["timingPreview"] == {"issues": [], "issueCount": 0, "issuesTruncated": False}

    workspace.flow.data["steps"][0]["state"] = "Success"
    (Path(workspace.directory) / "sta_ecc" / "analysis" / "sta_timing_issues.json").write_text(
        "not json", encoding="utf-8"
    )
    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")
    assert snapshot["timingPreview"] == {"issues": [], "issueCount": 0, "issuesTruncated": False}


def test_hotspot_preview_flattens_steps_and_ranks_by_severity(tmp_path):
    workspace = _workspace(
        tmp_path,
        [
            {"name": "place", "tool": "dreamplace", "state": "Success"},
            {"name": "Route", "tool": "ecc", "state": "Success"},
        ],
    )
    root = Path(workspace.directory)
    _write_json(
        root / "place_dreamplace" / "analysis" / "qor_hotspots.json",
        {
            "schema_version": 3,
            "hotspots": [
                {
                    "kind": "congestion",
                    "severity": "warning",
                    "metric_id": f"place_hotspot_{i}",
                    "display_name": f"Place Hotspot {i}",
                    "value": i + 1,
                    "unit": "count",
                    "category": "routability_physical",
                    "source": {"kind": "metrics"},
                    "description": "warning hotspot",
                }
                for i in range(4)
            ],
        },
    )
    _write_json(
        root / "Route_ecc" / "analysis" / "qor_hotspots.json",
        {
            "schema_version": 3,
            "hotspots": [
                {
                    "kind": "routing_violation",
                    "severity": "critical",
                    "metric_id": "route_dr_total_violation_count",
                    "display_name": "DR Violations",
                    "value": 12,
                    "unit": "count",
                    "category": "routability_physical",
                    "source": {"kind": "metrics"},
                    "description": "critical hotspot",
                }
            ],
        },
    )

    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    preview = snapshot["hotspotPreview"]
    assert preview["hotspotCount"] == 5
    assert preview["hotspotsTruncated"] is False
    assert preview["hotspots"][0]["severity"] == "critical"
    assert preview["hotspots"][0]["stepId"] == "Route"
    assert [hotspot["stepId"] for hotspot in preview["hotspots"][1:]] == ["place"] * 4
    assert all("source" not in hotspot for hotspot in preview["hotspots"])


def test_hotspot_preview_truncates_to_top5(tmp_path):
    workspace = _workspace(tmp_path, [{"name": "Route", "tool": "ecc", "state": "Success"}])
    _write_json(
        Path(workspace.directory) / "Route_ecc" / "analysis" / "qor_hotspots.json",
        {
            "schema_version": 3,
            "hotspots": [
                {
                    "kind": "routing_overflow",
                    "severity": "critical",
                    "metric_id": f"route_hotspot_{index}",
                    "value": index,
                }
                for index in range(7)
            ],
        },
    )

    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    preview = snapshot["hotspotPreview"]
    assert preview["hotspotCount"] == 7
    assert preview["hotspotsTruncated"] is True
    assert len(preview["hotspots"]) == 5


def test_checklist_projection_drops_evidence_and_source(tmp_path):
    workspace = _workspace(tmp_path, [])
    _write_json(
        Path(workspace.directory) / "home" / "checklist.json",
        {
            "schema_version": 3,
            "kind": "signoff_checklist",
            "status": "attention",
            "checklist": [
                {
                    "id": "sta.timing_signoff",
                    "step": "sta",
                    "category": "timing",
                    "owner": "qor",
                    "policy": "block",
                    "state": "failed",
                    "blocked": True,
                    "title": "Timing signoff",
                    "summary": "Setup violations remain",
                    "source": {"path": "sta_ecc/analysis/sta_timing_issues.json"},
                    "evidence": [{"kind": "file", "path": "sta_ecc/report/sta.rpt"}],
                }
            ],
        },
    )

    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    assert snapshot["checklist"] == {
        "items": [
            {
                "id": "sta.timing_signoff",
                "title": "Timing signoff",
                "state": "failed",
                "blocked": True,
                "step": "sta",
                "category": "timing",
                "summary": "Setup violations remain",
            }
        ]
    }
    assert snapshot["signoffAssessment"]["status"] == "attention"


def test_checklist_projection_is_empty_without_valid_checklist(tmp_path):
    workspace = _workspace(tmp_path, [])

    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    assert snapshot["checklist"] == {"items": []}


def test_workspace_checklist_is_indexed_as_workspace_level_artifact(tmp_path):
    workspace = _workspace(tmp_path, [])
    _write_json(
        Path(workspace.directory) / "home" / "checklist.json",
        {"schema_version": 3, "kind": "signoff_checklist", "checklist": []},
    )

    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    checklist_artifacts = [
        artifact for artifact in snapshot["artifacts"] if artifact["kind"] == "checklist"
    ]
    assert checklist_artifacts == [
        {
            "artifactId": "artifact-"
            + hashlib.sha256(b"engineering-gcd\0home/checklist.json").hexdigest()[:32],
            "kind": "checklist",
            "name": "checklist.json",
            "stepId": "",
            "reference": "home/checklist.json",
            "availability": "available",
        }
    ]


def test_workspace_checklist_artifact_is_absent_without_checklist_file(tmp_path):
    workspace = _workspace(tmp_path, [])

    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    assert [artifact for artifact in snapshot["artifacts"] if artifact["kind"] == "checklist"] == []
