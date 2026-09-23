import json
from types import SimpleNamespace

from chipcompiler.engine.qor import build_workspace_qor_assessment
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


def _success_step(step_id, records, *, order=0, quality_status="pass"):
    return {
        "stepId": step_id,
        "order": order,
        "flowState": "Success",
        "metrics": {"status": "available", "data": {"metrics": records}},
        "summary": {
            "status": "available",
            "data": {"schema_version": 4, "quality_status": quality_status},
        },
    }


def test_assessment_is_pure_data_without_scoring_fields():
    metric = _metric_record()
    analysis = {"steps": [_success_step("Harden", [metric])]}

    assessment = build_workspace_qor_assessment(analysis)

    assert assessment == {
        "status": "ready",
        "metrics": [metric],
        "steps": [
            {
                "stepId": "Harden",
                "order": 0,
                "name": "Harden",
                "status": "pass",
                "summaryMetricCount": 1,
            }
        ],
    }


def test_assessment_collects_only_success_steps_and_valid_metrics():
    valid = _metric_record()
    invalid = _metric_record(value=float("nan"))
    analysis = {
        "steps": [
            _success_step("Synthesis", [valid, invalid]),
            {
                "stepId": "place",
                "order": 1,
                "flowState": "Ongoing",
                "metrics": {"status": "available", "data": {"metrics": [_metric_record()]}},
                "summary": {"status": "missing", "data": None},
            },
        ]
    }

    assessment = build_workspace_qor_assessment(analysis)

    assert assessment["status"] == "ready"
    assert assessment["metrics"] == [valid]
    assert [step["stepId"] for step in assessment["steps"]] == ["Synthesis"]


def test_assessment_without_success_step_metrics_is_unavailable():
    analysis = {
        "steps": [
            _success_step("Synthesis", []),
            {
                "stepId": "place",
                "order": 1,
                "flowState": "Unstart",
                "metrics": {"status": "missing", "data": None},
                "summary": {"status": "missing", "data": None},
            },
        ]
    }

    assessment = build_workspace_qor_assessment(analysis)

    assert assessment == {
        "status": "unavailable",
        "metrics": [],
        "steps": [
            {
                "stepId": "Synthesis",
                "order": 0,
                "name": "Synthesis",
                "status": "pass",
                "summaryMetricCount": 0,
            }
        ],
    }


def _workspace(tmp_path, records):
    root = tmp_path / "workspace"
    (root / "home").mkdir(parents=True)
    steps = [{"name": "Harden", "tool": "ecc", "state": "Success"}]
    (root / "home" / "flow.json").write_text(json.dumps({"steps": steps}), encoding="utf-8")
    analysis_dir = root / "Harden_ecc" / "analysis"
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "qor_metrics.json").write_text(
        json.dumps({"schema_version": 3, "metrics": records}), encoding="utf-8"
    )
    (analysis_dir / "qor_summary.json").write_text(
        json.dumps(
            {
                "schema_version": 4,
                "analysis_status": "valid",
                "quality_status": "pass",
                "gates": [],
                "missing_metrics": [],
            }
        ),
        encoding="utf-8",
    )
    (analysis_dir / "qor_hotspots.json").write_text(
        json.dumps({"schema_version": 3, "hotspots": []}), encoding="utf-8"
    )
    return SimpleNamespace(
        directory=root,
        flow=SimpleNamespace(data={"steps": steps}),
        home=SimpleNamespace(data={}),
        parameters=SimpleNamespace(data={"design": "gcd"}),
        design=SimpleNamespace(name="gcd"),
    )


def test_snapshot_pairs_data_only_assessment_with_qor_v3_extension(tmp_path):
    metric = _metric_record()
    workspace = _workspace(tmp_path, [metric])

    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    assessment = snapshot["qorAssessment"]
    assert set(assessment) == {"status", "metrics", "steps"}
    assert assessment["status"] == "ready"
    assert assessment["metrics"] == [metric]
    assert snapshot["metrics"] == [metric]
    assert snapshot["metrics"] is not assessment["metrics"]
    extension = snapshot["qorSnapshotExtension"]
    assert extension["scoringEngine"] == "qor-v3"
    assert extension["status"] == "available"


def test_snapshot_keeps_unavailable_assessment_when_extension_analysis_fails(tmp_path, monkeypatch):
    metric = _metric_record()
    workspace = _workspace(tmp_path, [metric])

    def fail(_workspace):
        raise RuntimeError("broken analysis")

    monkeypatch.setattr("chipcompiler.analysis.qor.build_qor_analysis", fail)

    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-gcd")

    assert snapshot["qorSnapshotExtension"]["status"] == "unavailable"
    assert snapshot["qorAssessment"] == {
        "status": "ready",
        "metrics": [metric],
        "steps": [
            {
                "stepId": "Harden",
                "order": 0,
                "name": "Harden",
                "status": "pass",
                "summaryMetricCount": 1,
            }
        ],
    }
    assert snapshot["metrics"] == [metric]


def test_analysis_maps_legacy_power_category_to_power_integrity(tmp_path):
    from chipcompiler.engine.analysis import _analysis_file
    from chipcompiler.utility import json_write

    path = tmp_path / "qor_metrics.json"
    json_write(
        path,
        {
            "schema_version": 3,
            "metrics": [
                {
                    "id": "synthesis_power_dynamic_uw",
                    "display_name": "Synthesis Dynamic Power",
                    "value": 18.5,
                    "category": "power",
                    "direction": "trend_only",
                    "scope": "synthesis",
                    "rating": {"gate": False, "score": False, "trend": True},
                }
            ],
        },
    )

    payload = _analysis_file(path, "artifact-metrics", 3, tmp_path)
    assert payload["status"] == "available"
    assert payload["data"]["metrics"][0]["category"] == "power_integrity"
