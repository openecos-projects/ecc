from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.tools.ecc.runner import _write_floorplan_parameter_runtime_report


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


def test_runtime_report_records_native_core_utilization_consumer(tmp_path):
    _write_candidate(tmp_path, "floorplan.core_util", 0.8)
    config_path = _write_config(tmp_path, mode="die_util", field="utilization", value=0.8)

    _write_floorplan_parameter_runtime_report(SimpleNamespace(directory=tmp_path), config_path)

    report = json.loads((tmp_path / "analysis" / "parameter_runtime_report.v1.json").read_text())
    assert report["activation"]["status"] == "used"
    assert report["activation"]["consumers"][0]["consumer_id"] == (
        "ifp.die_builder.die_utilization"
    )
    assert report["effective_final"] == {"value": 0.8, "unit": "ratio"}


def test_runtime_report_records_native_aspect_ratio_consumer(tmp_path):
    _write_candidate(tmp_path, "floorplan.aspect_ratio", 1.25)
    config_path = _write_config(tmp_path, mode="die_util", field="aspect_ratio", value=1.25)

    _write_floorplan_parameter_runtime_report(SimpleNamespace(directory=tmp_path), config_path)

    report = json.loads((tmp_path / "analysis" / "parameter_runtime_report.v1.json").read_text())
    assert report["activation"]["status"] == "used"
    assert report["activation"]["consumers"][0]["consumer_id"] == (
        "ifp.die_builder.die_aspect_ratio"
    )


def test_runtime_report_marks_die_size_mode_not_activated(tmp_path):
    _write_candidate(tmp_path, "floorplan.core_util", 0.8)
    config_path = _write_config(tmp_path, mode="die_size", field="utilization", value=0.8)

    _write_floorplan_parameter_runtime_report(SimpleNamespace(directory=tmp_path), config_path)

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
