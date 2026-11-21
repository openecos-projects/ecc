import json
from typing import Any
from unittest.mock import Mock, call

import pytest

from chipcompiler.data import (
    EccFeature,
    EccReport,
    EccStep,
    OriginDesign,
    StepEnum,
    Workspace,
)
from chipcompiler.tools.ecc import builder, runner
from chipcompiler.tools.ecc.antenna import (
    antenna_check_metrics,
    antenna_coverage,
    read_antenna_check,
)
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.tools.ecc.signoff_checklist import _step_artifact_items
from chipcompiler.utility import json_read


@pytest.fixture
def antenna_case(tmp_path, monkeypatch):
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd", top_module="gcd"))
    step = builder.build_step(
        workspace,
        StepEnum.ANTENNA_CHECK.value,
        input_def=tmp_path / "drc_ecc" / "output" / "gcd_drc.def.gz",
        input_verilog=tmp_path / "drc_ecc" / "output" / "gcd_drc.v.gz",
    )
    builder.build_step_space(step)
    native_report = (
        step.data.steps[StepEnum.ANTENNA_CHECK.value] / "antenna_checker" / "antenna_check.rpt"
    )
    module = Mock(spec=ECCToolsModule)
    module.init_mj.return_value = True
    module.destroy_mj.return_value = True

    def check_antenna(*, step_json):
        native_report.parent.mkdir(parents=True, exist_ok=True)
        native_report.write_text("Total Violations: 3\n", encoding="utf-8")
        step_json.parent.mkdir(parents=True, exist_ok=True)
        step_json.write_text(
            '{"schema_version": 1, "step": "antenna_check", "violations": []}\n',
            encoding="utf-8",
        )
        return True

    module.check_antenna.side_effect = check_antenna
    save_data = Mock(return_value=True)
    monkeypatch.setattr(runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(runner, "save_data", save_data)
    return workspace, step, module, native_report, save_data


def test_antenna_dispatch_publishes_report_and_continues_with_violations(antenna_case):
    workspace, step, module, native_report, save_data = antenna_case

    assert runner.run_step(workspace, step, module) is True

    assert module.method_calls == [
        call.update_step_paths(output_dir=step.data.dir, feature_dir=step.feature.dir),
        call.init_mj(output_dir=workspace.directory / "antenna_check_ecc" / "data" / "mj"),
        call.check_antenna(step_json=step.feature.step),
        call.destroy_mj(),
    ]
    assert step.report.step.read_bytes() == native_report.read_bytes() == b"Total Violations: 3\n"
    assert json_read(step.feature.step)["step"] == "antenna_check"
    save_data.assert_called_once_with(
        workspace=workspace, step=step, ecc_module=module, feature_step=False
    )
    persisted = json_read(step.subflow.path)
    assert [(item["name"], item["state"]) for item in persisted["steps"]] == [
        ("load data", "Success"),
        ("check antenna", "Success"),
        ("save data", "Success"),
    ]


def test_antenna_run_warns_when_nothing_was_analysed(antenna_case, monkeypatch):
    workspace, step, module, _native_report, _save_data = antenna_case
    original = module.check_antenna.side_effect

    def vacuous(*, step_json):
        original(step_json=step_json)
        step_json.write_text(
            '{"antenna_check": {"signal_net_count": 0, "pins_with_gate_area": 0,'
            ' "violation_count": 0}}\n',
            encoding="utf-8",
        )
        return True

    module.check_antenna.side_effect = vacuous
    warnings = []
    monkeypatch.setattr(
        workspace.logger, "warning", lambda msg, *args: warnings.append(msg % args if args else msg)
    )

    assert runner.run_step(workspace, step, module) is True

    assert any("not verified" in w for w in warnings)


@pytest.mark.parametrize("failed_method", ["init_mj", "check_antenna", "destroy_mj"])
def test_antenna_native_failure_releases_resources_without_saving(antenna_case, failed_method):
    workspace, step, module, _native_report, save_data = antenna_case
    method = getattr(module, failed_method)
    method.side_effect = None
    method.return_value = False

    assert runner.run_step(workspace, step, module) is False

    assert module.check_antenna.call_count == (failed_method != "init_mj")
    assert module.destroy_mj.call_count == (failed_method != "init_mj")
    assert not step.report.step.exists()
    save_data.assert_not_called()
    assert [(item["name"], item["state"]) for item in step.subflow.steps] == [
        ("load data", "Success"),
        ("check antenna", "Incomplete"),
        ("save data", "Unstart"),
    ]


@pytest.mark.parametrize("failed_method", ["init_mj", "check_antenna", "destroy_mj"])
def test_antenna_exception_releases_resources_and_marks_failure(antenna_case, failed_method):
    workspace, step, module, _native_report, save_data = antenna_case
    getattr(module, failed_method).side_effect = RuntimeError("native failure")

    with pytest.raises(RuntimeError, match="native failure"):
        runner.run_step(workspace, step, module)

    assert module.destroy_mj.call_count == (failed_method != "init_mj")
    assert not step.report.step.exists()
    save_data.assert_not_called()
    assert [(item["name"], item["state"]) for item in step.subflow.steps] == [
        ("load data", "Success"),
        ("check antenna", "Incomplete"),
        ("save data", "Unstart"),
    ]


def test_antenna_requires_a_fresh_report_on_rerun(antenna_case):
    workspace, step, module, native_report, save_data = antenna_case
    assert runner.run_step(workspace, step, module) is True
    module.check_antenna.side_effect = None
    module.check_antenna.return_value = True
    save_data.reset_mock()

    assert runner.run_step(workspace, step, module) is False

    assert not native_report.exists()
    assert not step.report.step.exists()
    save_data.assert_not_called()
    assert [(item["name"], item["state"]) for item in step.subflow.steps][:2] == [
        ("load data", "Success"),
        ("check antenna", "Incomplete"),
    ]


def test_antenna_failed_load_discards_old_reports(antenna_case, monkeypatch):
    workspace, step, module, native_report, save_data = antenna_case
    assert runner.run_step(workspace, step, module) is True
    monkeypatch.setattr(runner, "get_eda_instance", lambda **kwargs: None)
    module.reset_mock()
    save_data.reset_mock()

    assert runner.run_step(workspace, step, module) is False

    assert not native_report.exists()
    assert not step.report.step.exists()
    assert module.method_calls == []
    save_data.assert_not_called()
    assert step.subflow.steps[0]["state"] == "Incomplete"


def test_antenna_save_failure_is_not_success(antenna_case):
    workspace, step, module, _native_report, save_data = antenna_case
    save_data.return_value = False

    assert runner.run_step(workspace, step, module) is False

    assert [(item["name"], item["state"]) for item in step.subflow.steps] == [
        ("load data", "Success"),
        ("check antenna", "Success"),
        ("save data", "Incomplete"),
    ]


@pytest.mark.parametrize("result", [True, False])
def test_antenna_wrapper_returns_native_result(result):
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = Mock()
    module.ecc.check_antenna.return_value = result

    assert module.check_antenna() is result

    assert module.ecc.method_calls == [call.check_antenna(config_dict={})]


def test_antenna_wrapper_passes_step_json_path_to_native_api():
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = Mock()
    module.ecc.check_antenna.return_value = True

    assert module.check_antenna(step_json="/workspace/feature/antenna_check.step.json") is True

    assert module.ecc.method_calls == [
        call.check_antenna(config_dict={"-step_json": "/workspace/feature/antenna_check.step.json"})
    ]


@pytest.mark.parametrize(
    ("block", "verified"),
    [
        ({"signal_net_count": 4213, "pins_with_gate_area": 9781, "violation_count": 0}, True),
        ({"signal_net_count": 0, "pins_with_gate_area": 0, "violation_count": 0}, False),
        ({"signal_net_count": 10, "pins_with_gate_area": 0}, False),
        ({"signal_net_count": 0, "pins_with_gate_area": 5}, False),
        ({"signal_net_count": -1, "pins_with_gate_area": 5}, False),
        ({"signal_net_count": 10, "pins_with_gate_area": 1.5}, False),
        ({"signal_net_count": True, "pins_with_gate_area": 5}, False),
        ({"violation_count": 0}, False),
        (None, False),
    ],
)
def test_antenna_coverage(block, verified):
    ok, message = antenna_coverage(block)
    assert ok is verified
    assert message


def test_zero_net_message_names_both_causes():
    _, message = antenna_coverage({"signal_net_count": 0, "pins_with_gate_area": 0})
    assert "0 nets" in message and "ANTENNAGATEAREA" in message


def _antenna_step(tmp_path, step_json: dict | None) -> Any:
    root = tmp_path / "antenna_check_ecc"
    step: Any = EccStep(
        name=StepEnum.ANTENNA_CHECK.value,
        directory=root,
        feature=EccFeature(dir=root / "feature", step=root / "feature" / "antenna_check.step.json"),
        report=EccReport(dir=root / "report", step=root / "report" / "antenna_check.rpt"),
    )
    step.report.step.parent.mkdir(parents=True)
    step.report.step.write_text("Total Violations: 0\n", encoding="utf-8")
    if step_json is not None:
        step.feature.dir.mkdir(parents=True)
        step.feature.step.write_text(json.dumps(step_json), encoding="utf-8")
    return step


def _coverage_item(tmp_path, step_json):
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd"))
    step = _antenna_step(tmp_path, step_json)
    items = {item["id"]: item for item in _step_artifact_items(workspace, step)}
    return items["quality.antenna.coverage"], items["artifact.antenna_check.report"]


def test_vacuous_antenna_check_is_a_warning_not_a_pass(tmp_path):
    block = {"signal_net_count": 0, "pins_with_gate_area": 0, "violation_count": 0}
    item, report = _coverage_item(tmp_path, {"antenna_check": block})
    assert item["state"] == "warning"
    assert item["policy"] == "warn"
    assert item["blocked"] is False
    assert "not verified" in item["summary"]
    assert report["state"] == "pass"


def test_missing_step_json_is_a_warning(tmp_path):
    item, _ = _coverage_item(tmp_path, None)
    assert item["state"] == "warning"


def test_analysed_antenna_check_passes_coverage(tmp_path):
    block = {"signal_net_count": 12, "pins_with_gate_area": 30, "violation_count": 0}
    item, _ = _coverage_item(tmp_path, {"antenna_check": block})
    assert item["state"] == "pass"
    step_json = tmp_path / "antenna_check_ecc" / "feature" / "antenna_check.step.json"
    assert read_antenna_check(step_json) == block
    assert antenna_check_metrics(step_json) == {
        "antenna_violation_count": 0,
        "antenna_signal_net_count": 12,
        "antenna_gate_pin_count": 30,
    }


def test_antenna_check_metrics_rejects_invalid_counts(tmp_path):
    step_json = tmp_path / "antenna_check.step.json"
    step_json.write_text(
        json.dumps(
            {
                "antenna_check": {
                    "violation_count": 1.5,
                    "signal_net_count": -2,
                    "pins_with_gate_area": True,
                }
            }
        ),
        encoding="utf-8",
    )
    assert antenna_check_metrics(step_json) == {}


def test_antenna_diagnostics_warn_on_dropped_geometry(tmp_path):
    block = {
        "signal_net_count": 12,
        "pins_with_gate_area": 30,
        "violation_count": 0,
        "skipped_segments": 2,
        "conductors_out_of_range": 1,
        "partial_areas_dropped": 3,
    }
    ok, message = antenna_coverage(block)
    assert ok is True
    assert "skipped_segments=2" in message
    assert "conductors_out_of_range=1" in message
    assert "partial_areas_dropped=3" in message

    item, _ = _coverage_item(tmp_path, {"antenna_check": block})
    assert item["state"] == "warning"
    assert "skipped_segments=2" in item["summary"]
