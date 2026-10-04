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


def _complete_optional_artifacts(workspace_dir: Path, design: str = "gcd") -> None:
    """Satisfy warn-policy optional package members so readiness can be PASS."""
    (workspace_dir / "Harden_ecc" / "output" / f"{design}_Harden.png").write_text("png\n")
    lec_report = workspace_dir / "postRouteLec_yosys_lec" / "report"
    lec_report.mkdir(parents=True, exist_ok=True)
    (lec_report / "equiv_failed.il").write_text("x\n")
    (lec_report / "equiv_failed.v").write_text("x\n")


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
    from chipcompiler.engine.signoff.catalog import lookup_item

    produced = {item["id"] for item in assessment.get("items") or []}
    assert produced
    assert [item_id for item_id in produced if lookup_item(item_id) is None] == []
    assert "quality.drc.clean" in produced
    assert "artifact.harden.gds" in produced
    assert "artifact.rcx.spef_outputs" in produced
    assert "provenance.initial.rtl" in produced
    assert "flow.drc.completed" in produced
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
