#!/usr/bin/env python

from pathlib import Path

import pytest

from chipcompiler.tools.ecc.sta_artifacts import (
    discard_sta_run_outputs,
    publish_sta_artifacts,
)


def _seed_sta_temp_outputs(work_dir: Path) -> None:
    timing_dir = work_dir / "timing_reporter"
    timing_dir.mkdir(parents=True)
    (timing_dir / "qor_summary.rpt").write_text("report\n", encoding="utf-8")
    (timing_dir / "qor_summary.json").write_text("{}\n", encoding="utf-8")
    sdf_dir = work_dir / "sdf_writer"
    sdf_dir.mkdir(parents=True)
    (sdf_dir / "gcd.sdf").write_text("(DELAYFILE\n)\n", encoding="utf-8")


def test_discard_sta_run_outputs_clears_only_requested_modes(tmp_path):
    work_dir = tmp_path / "data" / "sta"
    _seed_sta_temp_outputs(work_dir)
    report_dir = tmp_path / "report"
    feature_dir = tmp_path / "feature"
    report_dir.mkdir()
    feature_dir.mkdir()
    stale_report = report_dir / "power.rpt"
    stale_report.write_text("previous report\n", encoding="utf-8")
    stale_sdf = report_dir / "gcd.sdf"
    stale_sdf.write_text("previous sdf\n", encoding="utf-8")
    (feature_dir / "qor_summary.json").write_text("stale\n", encoding="utf-8")
    (feature_dir / "power_summary.json").write_text("stale\n", encoding="utf-8")

    discard_sta_run_outputs(work_dir, report_dir, feature_dir, ("structured",))

    assert stale_report.read_text(encoding="utf-8") == "previous report\n"
    assert stale_sdf.read_text(encoding="utf-8") == "previous sdf\n"
    assert not any(feature_dir.iterdir())
    assert not any((work_dir / "timing_reporter").iterdir())
    assert not any((work_dir / "sdf_writer").iterdir())


def test_publish_sta_artifacts_splits_report_and_structured_artifacts(tmp_path):
    work_dir = tmp_path / "data" / "sta"
    _seed_sta_temp_outputs(work_dir)
    report_dir = tmp_path / "report"
    feature_dir = tmp_path / "feature"

    publish_sta_artifacts(work_dir, report_dir, feature_dir, ("report", "structured"))

    assert sorted(path.name for path in report_dir.iterdir()) == [
        "gcd.sdf",
        "qor_summary.rpt",
    ]
    assert (feature_dir / "qor_summary.json").is_file()


def test_publish_sta_artifacts_rolls_back_when_publication_fails(tmp_path, monkeypatch):
    work_dir = tmp_path / "data" / "sta"
    _seed_sta_temp_outputs(work_dir)
    report_dir = tmp_path / "report"
    feature_dir = tmp_path / "feature"

    def fail_copy(*_args):
        raise OSError("copy failed")

    monkeypatch.setattr("chipcompiler.tools.ecc.sta_artifacts.copy_sta_artifact", fail_copy)

    with pytest.raises(OSError, match="copy failed"):
        publish_sta_artifacts(work_dir, report_dir, feature_dir, ("report", "structured"))

    assert not report_dir.exists()
    assert not feature_dir.exists()
