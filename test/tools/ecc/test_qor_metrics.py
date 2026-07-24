import json

from chipcompiler.tools.ecc.qor_metrics import QorMetrics


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_qor_metrics_reads_schema_v3_numeric_metric(tmp_path):
    path = tmp_path / "analysis" / "qor_metrics.json"
    _write(path, {"schema_version": 3, "metrics": [{"id": "route_wirelength", "value": 42.5}]})

    value, error = QorMetrics(path).number("route_wirelength")

    assert value == 42.5
    assert error is None


def test_qor_metrics_reports_missing_current_metric(tmp_path):
    path = tmp_path / "analysis" / "qor_metrics.json"
    _write(path, {"schema_version": 3, "metrics": []})

    value, error = QorMetrics(path).number("drc_count")

    assert value is None
    assert error == "drc_count is missing from qor_metrics.json"


def test_qor_metrics_rejects_legacy_schema(tmp_path):
    path = tmp_path / "analysis" / "qor_metrics.json"
    _write(path, {"schema_version": 2, "metrics": []})

    value, error = QorMetrics(path).number("drc_count")

    assert value is None
    assert error == "qor_metrics.json does not use schema_version 3"
