from pathlib import Path
from unittest.mock import Mock

from chipcompiler.data import EccData, EccFeature, EccStep, StepEnum, Workspace
from chipcompiler.data.step import STEP_DIRECTORIES
from chipcompiler.tools.ecc import runner as ecc_runner
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.tools.ecc.sta_qor import (
    STA_POWER_REPORT_FILENAME,
    STA_POWER_SUMMARY_FILENAME,
    read_sta_power_summary_json,
)
from chipcompiler.tools.ecc.subflow import EccSubFlow, EccSubFlowEnum

POWER_REPORT_TEXT = """\
Cell Internal Power  =    1.0000 mW
Net Switching Power  =    2.0000 mW
Total Dynamic Power  =    3.0000 mW
Cell Leakage Power   =    4.0000 uW
"""


class FakePowerModule(ECCToolsModule):
    def __init__(self):
        self.calls = []
        self.output_dir = None
        self.emit_report = True

    def update_step_paths(self, output_dir, feature_dir):
        self.calls.append(
            ("update_step_paths", {"output_dir": output_dir, "feature_dir": feature_dir})
        )

    def init_pw(self, output_dir):
        self.calls.append(("init_pw", output_dir))
        self.output_dir = Path(output_dir)
        return True

    def run_pw(self):
        self.calls.append(("run_pw",))
        if self.emit_report:
            power_report_dir = self.output_dir / "power_reporter"
            power_report_dir.mkdir(parents=True)
            (power_report_dir / STA_POWER_REPORT_FILENAME).write_text(POWER_REPORT_TEXT)
        return True

    def destroy_pw(self):
        self.calls.append(("destroy_pw",))
        return True


class FakeSubFlow:
    def __init__(self, **_kwargs):
        self.updates = []

    def update_step(self, **kwargs):
        self.updates.append(kwargs)


def test_power_analysis_uses_its_own_data_directory_and_native_lifecycle(tmp_path, monkeypatch):
    power_data_dir = tmp_path / "powerAnalysis_ecc" / "data" / "pw"
    step = EccStep(
        name=StepEnum.POWER_ANALYSIS.value,
        data=EccData(
            dir=tmp_path / "powerAnalysis_ecc" / "data",
            steps={StepEnum.POWER_ANALYSIS.value: power_data_dir},
        ),
        feature=EccFeature(dir=tmp_path / "powerAnalysis_ecc" / "feature"),
    )
    module = FakePowerModule()
    monkeypatch.setattr(ecc_runner, "EccSubFlow", FakeSubFlow)
    monkeypatch.setattr(
        ecc_runner,
        "save_data",
        lambda **_kwargs: module.calls.append(("save_data",)) or True,
    )
    monkeypatch.setattr(
        ecc_runner,
        "run_analysis",
        lambda **_kwargs: module.calls.append(("run_analysis",)),
    )

    assert ecc_runner.run_power_analysis(Workspace(directory=tmp_path), step, module) is True
    assert module.calls == [
        (
            "update_step_paths",
            {"output_dir": step.data.dir, "feature_dir": step.feature.dir},
        ),
        ("init_pw", power_data_dir),
        ("run_pw",),
        ("destroy_pw",),
        ("save_data",),
        ("run_analysis",),
    ]
    assert (power_data_dir / "power_reporter" / STA_POWER_REPORT_FILENAME).is_file()
    assert read_sta_power_summary_json(step.feature.dir / STA_POWER_SUMMARY_FILENAME) is not None


def test_power_analysis_requires_native_power_report(tmp_path, monkeypatch):
    power_data_dir = tmp_path / "powerAnalysis_ecc" / "data" / "pw"
    step = EccStep(
        name=StepEnum.POWER_ANALYSIS.value,
        data=EccData(
            dir=tmp_path / "powerAnalysis_ecc" / "data",
            steps={StepEnum.POWER_ANALYSIS.value: power_data_dir},
        ),
        feature=EccFeature(dir=tmp_path / "powerAnalysis_ecc" / "feature"),
    )
    module = FakePowerModule()
    module.emit_report = False
    stale_report = power_data_dir / "power_reporter" / STA_POWER_REPORT_FILENAME
    stale_report.parent.mkdir(parents=True)
    stale_report.write_text("stale power\n")
    stale_summary = step.feature.dir / STA_POWER_SUMMARY_FILENAME
    stale_summary.parent.mkdir(parents=True)
    stale_summary.write_text("{}\n")
    monkeypatch.setattr(ecc_runner, "EccSubFlow", FakeSubFlow)

    assert ecc_runner.run_power_analysis(Workspace(directory=tmp_path), step, module) is False
    assert not stale_report.exists()
    assert not stale_summary.exists()
    assert module.calls == [
        (
            "update_step_paths",
            {"output_dir": step.data.dir, "feature_dir": step.feature.dir},
        ),
        ("init_pw", power_data_dir),
        ("run_pw",),
        ("destroy_pw",),
    ]


def test_power_analysis_native_module_methods_forward_to_ecc(tmp_path):
    native = Mock()
    native.init_pw.return_value = True
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = native

    assert module.init_pw(tmp_path) is True
    assert module.run_pw() is native.run_pw.return_value
    assert module.destroy_pw() is native.destroy_pw.return_value
    native.init_pw.assert_called_once_with(config_dict={"-temp_directory_path": str(tmp_path)})
    native.run_pw.assert_called_once_with()
    native.destroy_pw.assert_called_once_with()


def test_run_step_dispatches_power_analysis(monkeypatch):
    workspace = Workspace()
    step = EccStep(name=StepEnum.POWER_ANALYSIS.value)
    run_power_analysis = Mock(return_value=True)
    monkeypatch.setattr(ecc_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(ecc_runner, "run_power_analysis", run_power_analysis)

    assert ecc_runner.run_step(workspace, step) is True
    run_power_analysis.assert_called_once_with(workspace=workspace, step=step, ecc_module=None)


def test_power_analysis_subflow_and_directory_contract(tmp_path):
    step = EccStep(
        name=StepEnum.POWER_ANALYSIS.value,
        subflow=Mock(path=tmp_path / "subflow.json", steps=[]),
    )
    EccSubFlow(Workspace(directory=tmp_path), step)

    assert STEP_DIRECTORIES[StepEnum.POWER_ANALYSIS.value] == "powerAnalysis_ecc"
    assert [item["name"] for item in step.subflow.steps] == [
        EccSubFlowEnum.load_data.value,
        EccSubFlowEnum.run_power_analysis.value,
        EccSubFlowEnum.save_data.value,
        EccSubFlowEnum.analysis.value,
    ]
