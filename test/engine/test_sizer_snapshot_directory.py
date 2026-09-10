import json
from types import SimpleNamespace

from chipcompiler.engine.snapshot import create_engineering_snapshot


def test_snapshot_resolves_canonical_sizer_step_directory(tmp_path):
    step_dir = tmp_path / "timing_optimization_sizer"
    analysis = step_dir / "analysis"
    output = step_dir / "output"
    report = step_dir / "report"
    analysis.mkdir(parents=True)
    output.mkdir()
    report.mkdir()
    metric = {
        "id": "instance_count",
        "display_name": "Instance Count",
        "value": 298,
        "unit": "count",
        "category": "area_cost",
        "direction": "trend_only",
        "scope": "timing_optimization",
        "corner": None,
        "analysis_group": "timing optimization_metrics",
        "rating": {"gate": False, "score": False, "trend": True},
        "project_role": "trend",
        "step_role": "primary",
        "confidence": "high",
        "source": {},
    }
    (analysis / "qor_metrics.json").write_text(
        json.dumps({"schema_version": 3, "metrics": [metric]}), encoding="utf-8"
    )
    (analysis / "qor_summary.json").write_text(
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
    (analysis / "qor_hotspots.json").write_text(
        json.dumps({"schema_version": 3, "hotspots": []}), encoding="utf-8"
    )
    (output / "gcd_Timing optimization.png").write_bytes(b"layout")
    (report / "Timing optimization.db.rpt").write_text("report", encoding="utf-8")
    (step_dir / "subflow.json").write_text(
        json.dumps({"steps": [{"name": "run sizer", "state": "Success"}]}),
        encoding="utf-8",
    )
    workspace = SimpleNamespace(
        directory=tmp_path,
        design=SimpleNamespace(name="gcd"),
        flow=SimpleNamespace(
            data={
                "steps": [
                    {
                        "name": "Timing optimization",
                        "tool": "sizer",
                        "state": "Success",
                    }
                ]
            }
        ),
        parameters=SimpleNamespace(data={}),
        home=SimpleNamespace(data={}),
    )

    snapshot = create_engineering_snapshot(workspace, workspace_id="engineering-a")

    step = snapshot["analysis"]["steps"][0]
    assert step["stepId"] == "Timing optimization"
    assert step["metrics"]["data"]["metrics"] == [metric]
    assert step["subflow"]["status"] == "available"
    artifacts = {artifact["kind"]: artifact for artifact in snapshot["artifacts"]}
    assert artifacts["qor_metrics"]["reference"] == (
        "timing_optimization_sizer/analysis/qor_metrics.json"
    )
    assert artifacts["qor_metrics"]["availability"] == "available"
    assert artifacts["layout_image"]["availability"] == "available"
    assert artifacts["layout_image"]["reference"] == (
        "timing_optimization_sizer/output/gcd_Timing optimization.png"
    )
    reports = [artifact for artifact in snapshot["artifacts"] if artifact["kind"] == "report_text"]
    assert reports[0]["availability"] == "available"
