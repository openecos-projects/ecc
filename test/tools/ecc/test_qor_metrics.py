import json
from pathlib import Path

from chipcompiler.data import StepEnum, Workspace
from chipcompiler.data.pdk import PDK
from chipcompiler.data.workspace.tool_configs import tool_config
from chipcompiler.tools.ecc.qor_metrics import QorMetrics
from chipcompiler.tools.ecc.sta_qor import configured_sta_artifact_directories

_STA_CONFIGS_DIR = Path(__file__).resolve().parents[3] / "chipcompiler/tools/ecc/configs"


def _default_sta_config():
    return tool_config(_STA_CONFIGS_DIR, "sta_ecc.json", PDK(name="ics55", version="v1"))


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
    _write(
        summary,
        {
            "schema_version": 4,
            "analysis_revision": "quality-gates-v4",
            "analysis_status": "valid",
            "quality_status": "pass",
            "gates": [],
        },
    )

    source = _harden_signoff_source(workspace, StepEnum.HARDEN.value)

    assert source["step"] == StepEnum.HARDEN.value
    assert source["available"] is True
    assert source["status"] == "pass"


def test_configured_sta_directories_follow_default_five_signoff_corners(tmp_path):
    config_path = tmp_path / "config" / "sta_ecc.json"
    config_path.parent.mkdir()
    config_path.write_text(json.dumps(_default_sta_config()), encoding="utf-8")
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


def test_qor_metrics_conflicting_duplicate_is_unknown_for_that_metric_only(tmp_path):
    path = tmp_path / "analysis" / "qor_metrics.json"
    _write(
        path,
        {
            "schema_version": 3,
            "metrics": [
                {"id": "drc_count", "value": 0},
                {"id": "drc_count", "value": 999},
                {"id": "lvs_count", "value": 0},
            ],
        },
    )
    metrics = QorMetrics(path)

    value, error = metrics.number("drc_count")
    assert value is None
    assert error == "qor_metrics.json contains conflicting duplicate metric id drc_count"
    assert metrics.number("lvs_count") == (0.0, None)


def test_qor_metrics_identical_duplicate_is_accepted(tmp_path):
    path = tmp_path / "analysis" / "qor_metrics.json"
    _write(
        path,
        {
            "schema_version": 3,
            "metrics": [{"id": "drc_count", "value": 0}, {"id": "drc_count", "value": 0}],
        },
    )

    assert QorMetrics(path).number("drc_count") == (0.0, None)


def test_qor_metrics_bool_vs_int_counts_as_conflict(tmp_path):
    path = tmp_path / "analysis" / "qor_metrics.json"
    _write(
        path,
        {
            "schema_version": 3,
            "metrics": [{"id": "drc_count", "value": 0}, {"id": "drc_count", "value": False}],
        },
    )

    value, error = QorMetrics(path).number("drc_count")
    assert value is None
    assert error == "qor_metrics.json contains conflicting duplicate metric id drc_count"
