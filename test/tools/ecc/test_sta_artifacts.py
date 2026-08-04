#!/usr/bin/env python

import json
from pathlib import Path

import pytest

from chipcompiler.tools.ecc.sta_artifacts import (
    discard_sta_run_outputs,
    publish_sta_artifacts,
)

POWER_REPORT = (
    "Cell Internal Power  =   51.2062 uW\n"
    "Net Switching Power  =   11.5906 uW\n"
    "Total Dynamic Power  =   62.7968 uW\n"
    "Cell Leakage Power   =    1.7151 uW\n"
)


def _seed_sta_temp_outputs(work_dir: Path, power_contents: str | None = POWER_REPORT) -> None:
    timing_dir = work_dir / "timing_reporter"
    timing_dir.mkdir(parents=True)
    (timing_dir / "qor_summary.rpt").write_text("report\n", encoding="utf-8")
    (timing_dir / "qor_summary.json").write_text("{}\n", encoding="utf-8")
    sdf_dir = work_dir / "sdf_writer"
    sdf_dir.mkdir(parents=True)
    (sdf_dir / "gcd.sdf").write_text("(DELAYFILE\n)\n", encoding="utf-8")
    if power_contents is not None:
        power_dir = work_dir / "power_reporter"
        power_dir.mkdir(parents=True)
        (power_dir / "power.rpt").write_text(power_contents, encoding="utf-8")


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
    assert not (work_dir / "power_reporter" / "power.rpt").exists()


def test_publish_sta_artifacts_splits_report_and_structured_artifacts(tmp_path):
    work_dir = tmp_path / "data" / "sta"
    _seed_sta_temp_outputs(work_dir)
    report_dir = tmp_path / "report"
    feature_dir = tmp_path / "feature"

    publish_sta_artifacts(work_dir, report_dir, feature_dir, ("report", "structured"))

    assert sorted(path.name for path in report_dir.iterdir()) == [
        "gcd.sdf",
        "power.rpt",
        "qor_summary.rpt",
    ]
    assert (feature_dir / "qor_summary.json").is_file()
    assert not (feature_dir / "power.rpt").exists()
    assert json.loads((feature_dir / "power_summary.json").read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "internal_uw": 51.2062,
        "switching_uw": 11.5906,
        "dynamic_uw": 62.7968,
        "leakage_uw": 1.7151,
    }


def test_publish_sta_artifacts_requires_power_report(tmp_path):
    work_dir = tmp_path / "data" / "sta"
    report_dir = tmp_path / "report"
    feature_dir = tmp_path / "feature"
    report_dir.mkdir(parents=True)
    feature_dir.mkdir()
    (report_dir / "power.rpt").write_text("stale\n", encoding="utf-8")
    # A rerun invalidates previous outputs before the native run; the native
    # run then produces timing reports but no power report.
    discard_sta_run_outputs(work_dir, report_dir, feature_dir, ("report", "structured"))
    _seed_sta_temp_outputs(work_dir, power_contents=None)

    with pytest.raises(FileNotFoundError, match="power report"):
        publish_sta_artifacts(work_dir, report_dir, feature_dir, ("report", "structured"))

    assert not any(report_dir.iterdir())
    assert not any(feature_dir.iterdir())


def test_publish_sta_artifacts_rejects_unparseable_power_report(tmp_path):
    work_dir = tmp_path / "data" / "sta"
    _seed_sta_temp_outputs(work_dir, power_contents="power estimate unavailable\n")

    with pytest.raises(ValueError, match="power report is not parseable"):
        publish_sta_artifacts(
            work_dir, tmp_path / "report", tmp_path / "feature", ("report", "structured")
        )

    assert not (tmp_path / "report").exists()
    assert not (tmp_path / "feature").exists()


def test_publish_sta_artifacts_rolls_back_when_publication_fails(tmp_path, monkeypatch):
    work_dir = tmp_path / "data" / "sta"
    _seed_sta_temp_outputs(work_dir)
    report_dir = tmp_path / "report"
    feature_dir = tmp_path / "feature"
    monkeypatch.setattr("chipcompiler.tools.ecc.sta_artifacts.json_write", lambda *args: False)

    with pytest.raises(OSError, match="power summary"):
        publish_sta_artifacts(work_dir, report_dir, feature_dir, ("report", "structured"))

    assert not any(report_dir.iterdir())
    assert not any(feature_dir.iterdir())
