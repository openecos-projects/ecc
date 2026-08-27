from __future__ import annotations

import json
from types import SimpleNamespace

from chipcompiler.tools.ecc_dreamplace.module import _write_parameter_runtime_report


def test_runtime_report_records_native_density_consumer(tmp_path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "candidate_materialization.v1.json").write_text(
        json.dumps({"patch": [{"knob_id": "place.target_density", "value": 0.85}]}),
        encoding="utf-8",
    )
    params = SimpleNamespace(target_density=0.85)
    _write_parameter_runtime_report(
        SimpleNamespace(directory=tmp_path), params, engine_succeeded=True
    )
    report = json.loads((analysis / "parameter_runtime_report.v1.json").read_text())
    assert report["activation"]["status"] == "used"
    assert report["activation"]["consumers"][0]["consumer_id"] == "dreamplace.density_objective"


def test_runtime_report_marks_disabled_routability_not_activated(tmp_path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "candidate_materialization.v1.json").write_text(
        json.dumps({"patch": [{"knob_id": "place.routability_opt", "value": False}]}),
        encoding="utf-8",
    )
    _write_parameter_runtime_report(
        SimpleNamespace(directory=tmp_path), SimpleNamespace(routability_opt_flag=False)
    )
    report = json.loads((analysis / "parameter_runtime_report.v1.json").read_text())
    assert report["activation"]["status"] == "not_activated"


def test_runtime_report_requires_a_native_routability_round(tmp_path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "candidate_materialization.v1.json").write_text(
        json.dumps({"patch": [{"knob_id": "place.routability_opt", "value": True}]}),
        encoding="utf-8",
    )
    _write_parameter_runtime_report(
        SimpleNamespace(directory=tmp_path),
        SimpleNamespace(routability_opt_flag=True),
        engine_succeeded=True,
    )
    report = json.loads((analysis / "parameter_runtime_report.v1.json").read_text())
    assert report["activation"]["status"] == "not_activated"
    assert report["consumer_observation"]["evidence_complete"] is False

    log_dir = tmp_path / "place_dreamplace" / "log"
    log_dir.mkdir(parents=True)
    (log_dir / "place.log").write_text(
        "routability optimization round 0: adjust area flags = (1, 1, 0)\n",
        encoding="utf-8",
    )
    _write_parameter_runtime_report(
        SimpleNamespace(directory=tmp_path),
        SimpleNamespace(routability_opt_flag=True),
        engine_succeeded=True,
    )
    report = json.loads((analysis / "parameter_runtime_report.v1.json").read_text())
    assert report["activation"]["status"] == "used"
    assert report["consumer_observation"]["branch_round_count"] == 1


def test_runtime_report_does_not_claim_use_before_engine_success(tmp_path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "candidate_materialization.v1.json").write_text(
        json.dumps({"patch": [{"knob_id": "place.target_density", "value": 0.85}]}),
        encoding="utf-8",
    )
    _write_parameter_runtime_report(
        SimpleNamespace(directory=tmp_path), SimpleNamespace(target_density=0.85)
    )
    report = json.loads((analysis / "parameter_runtime_report.v1.json").read_text())
    assert report["activation"] == {"status": "unknown", "consumers": []}
