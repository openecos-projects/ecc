"""Mock-workspace signoff flow: artifacts → readiness → package (no ICS55 PDK)."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest
from test_signoff_package import _make_engine_flow, _make_signoff_workspace, _qor_gate, _qor_summary

from chipcompiler.engine.signoff import SignoffPackageOptions
from chipcompiler.engine.signoff_assessment import build_signoff_assessment
from chipcompiler.engine.signoff_export import SignoffExportError, export_signoff_package_archive


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _metrics_payload(*pairs: tuple[str, float]) -> dict:
    return {
        "schema_version": 3,
        "status": "success",
        "metrics": [{"id": metric_id, "value": value} for metric_id, value in pairs],
    }


def _complete_optional_artifacts(workspace_dir: Path, design: str = "gcd") -> None:
    """Satisfy warn-policy optional package members so readiness can be PASS."""
    (workspace_dir / "Harden_ecc" / "output" / f"{design}_Harden.png").write_text("png\n")
    lec_report = workspace_dir / "postRouteLec_yosys_lec" / "report"
    lec_report.mkdir(parents=True, exist_ok=True)
    (lec_report / "equiv_failed.il").write_text("x\n")
    (lec_report / "equiv_failed.v").write_text("x\n")
    # Performance slots are optional WARN; seed analysis metrics so they pass.
    _write_json(
        workspace_dir / "sta_ecc" / "analysis" / "qor_metrics.json",
        _metrics_payload(
            ("sta_setup_wns", 0.12),
            ("sta_setup_tns", 0.0),
            ("sta_hold_wns", 0.05),
            ("sta_hold_tns", 0.0),
            ("sta_frequency_mhz", 100.0),
            ("runtime_seconds", 10.0),
            ("peak_memory_mb", 512.0),
        ),
    )
    _write_json(
        workspace_dir / "powerAnalysis_ecc" / "analysis" / "qor_metrics.json",
        _metrics_payload(
            ("power_analysis_dynamic_uw", 1.0),
            ("power_analysis_leakage_uw", 0.1),
            ("runtime_seconds", 1.0),
            ("peak_memory_mb", 64.0),
        ),
    )
    _write_json(
        workspace_dir / "CTS_ecc" / "analysis" / "qor_metrics.json",
        _metrics_payload(
            ("cts_worst_optimized_skew_ns", 0.01),
            ("cts_worst_max_insertion_latency_ns", 0.2),
            ("cts_buffer_count", 3),
            ("cts_clock_wirelength_max", 100.0),
            ("cts_clock_tree_max_level", 2),
            ("runtime_seconds", 2.0),
            ("peak_memory_mb", 128.0),
        ),
    )
    _write_json(
        workspace_dir / "place_dreamplace" / "analysis" / "qor_metrics.json",
        _metrics_payload(
            ("place_hpwl", 1000.0),
            ("place_congestion_egr_overflow_total", 0.0),
            ("runtime_seconds", 3.0),
            ("peak_memory_mb", 256.0),
        ),
    )
    _write_json(
        workspace_dir / "route_ecc" / "analysis" / "qor_metrics.json",
        _metrics_payload(
            ("route_wirelength", 2000.0),
            ("route_via_count", 50),
            ("runtime_seconds", 4.0),
            ("peak_memory_mb", 200.0),
        ),
    )
    _write_json(
        workspace_dir / "Synthesis_yosys" / "analysis" / "qor_metrics.json",
        _metrics_payload(
            ("synthesis_cell_area", 100.0),
            ("synthesis_cell_count", 42),
            ("runtime_seconds", 5.0),
            ("peak_memory_mb", 300.0),
        ),
    )


def test_fixture_workspace_pass_and_export_archive(tmp_path: Path):
    workspace_dir = _make_signoff_workspace(tmp_path)
    _complete_optional_artifacts(workspace_dir)
    flow = _make_engine_flow(workspace_dir)

    collected = flow.collect_signoff_package(
        SignoffPackageOptions(archive=False, materialize=True, refresh_analysis=False)
    )
    assert collected.ok is True

    assessment = build_signoff_assessment(flow.workspace)
    assert assessment["status"] == "ready"
    assert assessment["readiness"] == "PASS"
    from chipcompiler.runtime.signoff.catalog import lookup_item

    produced = {item["id"] for item in assessment.get("items") or []}
    assert produced
    assert [item_id for item_id in produced if lookup_item(item_id) is None] == []
    assert "quality.drc.clean" in produced
    assert "artifact.harden.gds" in produced
    assert "artifact.rcx.spef_outputs" in produced
    assert "provenance.initial.rtl" in produced
    assert "flow.drc.completed" in produced
    assert "flow.cts.completed" in produced
    assert "configuration.cts" in produced
    assert "artifact.cts.feature" in produced
    assert "configuration.sta" in produced

    archive_path = tmp_path / "gcd_signoff.tar.gz"
    exported = export_signoff_package_archive(flow.workspace, str(archive_path))
    assert Path(exported).is_file()
    with tarfile.open(exported, "r:gz") as archive:
        names = archive.getnames()
    assert any(name.endswith("manifest.json") for name in names)
    assert any(name.endswith("summary.json") for name in names)


def test_fixture_workspace_drc_fail_is_error_and_blocks_export(tmp_path: Path):
    workspace_dir = _make_signoff_workspace(tmp_path)
    failed = _qor_summary(
        {
            **_qor_gate("qor.drc.clean", "Final DRC clean"),
            "state": "failed",
        }
    )
    failed["quality_status"] = "fail"
    _write_json(workspace_dir / "drc_ecc" / "analysis" / "qor_summary.json", failed)

    flow = _make_engine_flow(workspace_dir)
    collected = flow.collect_signoff_package(
        SignoffPackageOptions(archive=False, materialize=True, refresh_analysis=False)
    )
    assert collected.ok is False

    assessment = build_signoff_assessment(flow.workspace)
    assert assessment["status"] == "blocked"
    assert assessment["readiness"] == "ERROR"

    with pytest.raises(SignoffExportError, match="incomplete"):
        export_signoff_package_archive(flow.workspace, str(tmp_path / "blocked.tar.gz"))


def test_fixture_workspace_missing_spef_is_miss(tmp_path: Path):
    workspace_dir = _make_signoff_workspace(tmp_path)
    spef = next((workspace_dir / "RCX_ecc" / "output").glob("*.spef"))
    spef.unlink()

    flow = _make_engine_flow(workspace_dir)
    collected = flow.collect_signoff_package(
        SignoffPackageOptions(archive=False, materialize=True, refresh_analysis=False)
    )
    assert collected.ok is False

    assessment = build_signoff_assessment(flow.workspace)
    assert assessment["status"] == "blocked"
    assert assessment["readiness"] == "MISS"


def test_fixture_workspace_optional_gaps_are_warn(tmp_path: Path):
    # Default mock omits warn-policy optional members → attention / WARN.
    workspace_dir = _make_signoff_workspace(tmp_path)
    flow = _make_engine_flow(workspace_dir)
    collected = flow.collect_signoff_package(
        SignoffPackageOptions(archive=False, materialize=True, refresh_analysis=False)
    )
    assert collected.ok is True

    assessment = build_signoff_assessment(flow.workspace)
    assert assessment["status"] == "attention"
    assert assessment["readiness"] == "WARN"


def test_fixture_workspace_omits_cts_when_ledger_has_no_clock_tree(tmp_path: Path):
    workspace_dir = _make_signoff_workspace(tmp_path)
    flow_path = workspace_dir / "home" / "flow.json"
    data = json.loads(flow_path.read_text(encoding="utf-8"))
    data["steps"] = [step for step in data["steps"] if step.get("name") != "CTS"]
    flow_path.write_text(json.dumps(data), encoding="utf-8")

    flow = _make_engine_flow(workspace_dir)
    flow.collect_signoff_package(
        SignoffPackageOptions(archive=False, materialize=True, refresh_analysis=False)
    )
    assessment = build_signoff_assessment(flow.workspace)
    produced = {item["id"] for item in assessment.get("items") or []}
    assert "flow.cts.completed" not in produced
    assert "configuration.cts" not in produced
    assert "artifact.cts.feature" not in produced
    assert "quality.drc.clean" in produced
