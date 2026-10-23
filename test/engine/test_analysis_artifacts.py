from types import SimpleNamespace

from chipcompiler.engine.analysis import collect_workspace_projections


def test_step_analysis_artifacts_declare_required_evidence(tmp_path):
    workspace = SimpleNamespace(
        directory=tmp_path,
        flow=SimpleNamespace(data={"steps": [{"name": "sta", "tool": "ecc", "state": "Success"}]}),
        design=SimpleNamespace(name="gcd"),
    )

    artifacts = collect_workspace_projections(workspace, "ws-1")["artifacts"]
    by_kind = {artifact["kind"]: artifact for artifact in artifacts}

    assert by_kind["qor_metrics"]["required"] is True
    assert by_kind["qor_summary"]["required"] is True
    assert by_kind["sta_timing_issues"]["required"] is True
    assert by_kind["qor_hotspots"]["required"] is False
