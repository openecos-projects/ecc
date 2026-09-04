from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.tools.ecc.parameter_runtime_report import (
    _write_floorplan_parameter_runtime_report,
)


def _write_candidate(tmp_path: Path, knob_id: str, value: float) -> None:
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "candidate_materialization.v1.json").write_text(
        json.dumps({"patch": [{"knob_id": knob_id, "value": value}]}), encoding="utf-8"
    )


def _write_config(tmp_path: Path, *, mode: str, field: str, value: float) -> Path:
    config_path = tmp_path / "config" / "floorplan_ecc.json"
    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps({"die_builder": {"mode": mode, "die_util": {field: value}}}),
        encoding="utf-8",
    )
    return config_path


def _write_geometry_evidence(tmp_path: Path) -> tuple[Path, Path]:
    feature_path = tmp_path / "feature.json"
    feature_path.write_text(
        json.dumps(
            {
                "Design Layout": {
                    "core_area": 800.0,
                    "core_bounding_width": 40.0,
                    "core_bounding_height": 20.0,
                }
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.rpt"
    report_path.write_text("Number - Site | 120\nNumber - Row | 30\n", encoding="utf-8")
    return feature_path, report_path


def test_runtime_report_records_native_core_utilization_consumer(tmp_path):
    _write_candidate(tmp_path, "floorplan.core_util", 0.8)
    config_path = _write_config(tmp_path, mode="die_util", field="utilization", value=0.8)
    feature_path, report_path = _write_geometry_evidence(tmp_path)

    _write_floorplan_parameter_runtime_report(
        SimpleNamespace(directory=tmp_path),
        config_path,
        feature_path=feature_path,
        report_path=report_path,
    )

    report = json.loads((tmp_path / "analysis" / "parameter_runtime_report.v1.json").read_text())
    source_path = Path(_write_floorplan_parameter_runtime_report.__code__.co_filename)
    assert report["tool"] == {
        "name": "ECC-Floorplan",
        "revision": "ecc.floorplan.parameter_runtime_report.v2",
        "source_sha256": "sha256:" + hashlib.sha256(source_path.read_bytes()).hexdigest(),
    }
    assert report["activation"]["status"] == "used"
    assert report["activation"]["consumers"][0]["consumer_id"] == (
        "ifp.die_builder.die_utilization"
    )
    assert report["activation"]["consumers"][0]["outcome"] == "geometry_constructed"
    assert report["effective_final"] == {"value": 0.8, "unit": "ratio"}


def test_runtime_report_records_native_aspect_ratio_consumer(tmp_path):
    _write_candidate(tmp_path, "floorplan.aspect_ratio", 1.25)
    config_path = _write_config(tmp_path, mode="die_util", field="aspect_ratio", value=1.25)
    feature_path, report_path = _write_geometry_evidence(tmp_path)

    _write_floorplan_parameter_runtime_report(
        SimpleNamespace(directory=tmp_path),
        config_path,
        feature_path=feature_path,
        report_path=report_path,
    )

    report = json.loads((tmp_path / "analysis" / "parameter_runtime_report.v1.json").read_text())
    assert report["activation"]["status"] == "used"
    assert report["activation"]["consumers"][0]["consumer_id"] == (
        "ifp.die_builder.die_aspect_ratio"
    )
    assert report["activation"]["consumers"][0]["outcome"] == "geometry_constructed"


def test_runtime_report_does_not_claim_used_without_geometry_evidence(tmp_path):
    _write_candidate(tmp_path, "floorplan.core_util", 0.8)
    config_path = _write_config(tmp_path, mode="die_util", field="utilization", value=0.8)

    _write_floorplan_parameter_runtime_report(SimpleNamespace(directory=tmp_path), config_path)

    report = json.loads((tmp_path / "analysis" / "parameter_runtime_report.v1.json").read_text())
    assert report["application_status"] == "unknown"
    assert report["activation"] == {"status": "unknown", "consumers": []}


def test_runtime_report_marks_die_size_mode_not_activated(tmp_path):
    _write_candidate(tmp_path, "floorplan.core_util", 0.8)
    config_path = _write_config(tmp_path, mode="die_size", field="utilization", value=0.8)
    feature_path, report_path = _write_geometry_evidence(tmp_path)

    _write_floorplan_parameter_runtime_report(
        SimpleNamespace(directory=tmp_path),
        config_path,
        feature_path=feature_path,
        report_path=report_path,
    )

    report = json.loads((tmp_path / "analysis" / "parameter_runtime_report.v1.json").read_text())
    assert report["activation"]["status"] == "not_activated"


def test_runtime_report_does_not_claim_mismatched_native_value(tmp_path):
    _write_candidate(tmp_path, "floorplan.core_util", 0.8)
    config_path = _write_config(tmp_path, mode="die_util", field="utilization", value=0.7)

    _write_floorplan_parameter_runtime_report(SimpleNamespace(directory=tmp_path), config_path)

    report = json.loads((tmp_path / "analysis" / "parameter_runtime_report.v1.json").read_text())
    assert report["application_status"] == "unknown"
    assert report["activation"]["status"] == "unknown"
    assert report["activation"]["consumers"] == []


def test_runtime_report_records_native_core_geometry_rows_and_sites(tmp_path):
    _write_candidate(tmp_path, "floorplan.core_util", 0.8)
    config_path = _write_config(tmp_path, mode="die_util", field="utilization", value=0.8)
    feature_path = tmp_path / "feature.json"
    feature_path.write_text(
        json.dumps(
            {
                "Design Layout": {
                    "core_area": 800.0,
                    "core_bounding_width": 40.0,
                    "core_bounding_height": 20.0,
                }
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.rpt"
    report_path.write_text("Number - Site | 120\nNumber - Row | 30\n", encoding="utf-8")

    _write_floorplan_parameter_runtime_report(
        SimpleNamespace(directory=tmp_path),
        config_path,
        feature_path=feature_path,
        report_path=report_path,
    )

    report = json.loads((tmp_path / "analysis" / "parameter_runtime_report.v1.json").read_text())
    observation = report["consumer_observation"]
    assert observation["core_geometry"] == {
        "width": {"value": 40.0, "unit": "um"},
        "height": {"value": 20.0, "unit": "um"},
        "area": {"value": 800.0, "unit": "um^2"},
        "aspect_ratio": {"value": 2.0, "unit": "ratio"},
    }
    assert observation["rows"] == {"count": 30, "observed": True}
    assert observation["sites"] == {"count": 120, "observed": True}
