import json
from pathlib import Path

from chipcompiler.data import StepEnum, Workspace
from chipcompiler.tools.ecc.qor_metrics import QorMetrics
from chipcompiler.tools.ecc.sta_qor import configured_sta_artifact_directories


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


def test_harden_signoff_source_reads_the_step_directory_table(tmp_path):
    from chipcompiler.data import OriginDesign, StepEnum, Workspace
    from chipcompiler.data.step import STEP_DIRECTORIES
    from chipcompiler.tools.ecc.metrics import _harden_signoff_source

    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd"))
    summary = tmp_path / STEP_DIRECTORIES[StepEnum.HARDEN.value] / "analysis" / "qor_summary.json"
    _write(summary, {"schema_version": 3, "status": "pass", "hard_gates": []})

    source = _harden_signoff_source(workspace, StepEnum.HARDEN.value)

    assert source["step"] == StepEnum.HARDEN.value
    assert source["available"] is True
    assert source["status"] == "pass"


def test_configured_sta_directories_follow_default_five_signoff_corners(tmp_path):
    template = Path(__file__).resolve().parents[3] / "chipcompiler/tools/ecc/configs/sta_ecc.json"
    config_path = tmp_path / "config" / "sta_ecc.json"
    config_path.parent.mkdir()
    config_path.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    workspace = Workspace(directory=tmp_path, config={StepEnum.STA.value: config_path})

    directories = configured_sta_artifact_directories(
        workspace,
        tmp_path / "sta_ecc" / "report",
    )

    assert [corner for corner, _path in directories] == [
        "TYP_25/TYPICAL",
        "MIN_m40/Cworst",
        "MIN_m40/RCworst",
        "MIN_m40/Cbest",
        "MIN_m40/RCbest",
    ]
