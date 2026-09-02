from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.tools.ecc.runner import _write_cts_parameter_runtime_report


def _write_candidate(tmp_path: Path, value: int) -> None:
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "candidate_materialization.v1.json").write_text(
        json.dumps({"patch": [{"knob_id": "cts.max_fanout", "value": value}]}),
        encoding="utf-8",
    )


def test_cts_runtime_report_records_effective_value_without_claiming_activation(tmp_path):
    _write_candidate(tmp_path, 48)
    config = tmp_path / "config" / "cts_ecc.json"
    config.parent.mkdir()
    config.write_text('{"max_fanout": 48}', encoding="utf-8")

    _write_cts_parameter_runtime_report(
        SimpleNamespace(directory=tmp_path), config, engine_succeeded=True
    )

    report = json.loads((tmp_path / "analysis" / "parameter_runtime_report.v1.json").read_text())
    source = Path(_write_cts_parameter_runtime_report.__code__.co_filename)
    assert report["tool"] == {
        "name": "ECC-CTS",
        "revision": "ecc.cts.parameter_runtime_report.v1",
        "source_sha256": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    assert report["knob_id"] == "cts.max_fanout"
    assert report["requested_value"] == 48
    assert report["application_status"] == "applied"
    assert report["effective_final"] == {"value": 48, "unit": "fanout"}
    assert report["activation"] == {"status": "unknown", "consumers": []}
    assert report["consumer_observation"] == {
        "config_value": 48,
        "engine_succeeded": True,
        "activation_evidence_complete": False,
    }


def test_cts_runtime_report_rejects_mismatched_effective_value(tmp_path):
    _write_candidate(tmp_path, 48)
    config = tmp_path / "config" / "cts_ecc.json"
    config.parent.mkdir()
    config.write_text('{"max_fanout": 32}', encoding="utf-8")

    _write_cts_parameter_runtime_report(
        SimpleNamespace(directory=tmp_path), config, engine_succeeded=True
    )

    report = json.loads((tmp_path / "analysis" / "parameter_runtime_report.v1.json").read_text())
    assert report["application_status"] == "unknown"
    assert report["effective_final"] == {"value": 32, "unit": "fanout"}
