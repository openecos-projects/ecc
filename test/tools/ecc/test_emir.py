from pathlib import Path
from unittest.mock import Mock, call

import pytest

from chipcompiler.data import (
    OriginDesign,
    StepEnum,
    Workspace,
    build_workspace_config_paths,
    create_workspace,
)
from chipcompiler.data.workspace import refresh_workspace_config
from chipcompiler.tools.ecc import builder, runner
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.utility import json_read, json_write


def test_emir_default_technology_path_uses_packaged_resource(tmp_path, minimal_ics55_pdk_factory):
    fixtures = Path(__file__).resolve().parents[2] / "fixtures"
    workspace = create_workspace(
        directory=tmp_path / "workspace",
        origin_def="",
        origin_verilog=fixtures / "gcd/gcd.v",
        pdk="ics55",
        pdk_root=str(minimal_ics55_pdk_factory(tmp_path / "pdk")),
        parameters={},
    )

    technology_path = Path(json_read(workspace.config[StepEnum.EMIR.value])["technology_file_path"])

    assert technology_path.name == "ics55_synthetic.tech"
    assert technology_path.is_file()
    assert technology_path == Path(builder.__file__).parent / "configs" / technology_path.name


def test_emir_technology_override_survives_workspace_refresh(tmp_path, minimal_ics55_pdk_factory):
    fixtures = Path(__file__).resolve().parents[2] / "fixtures"
    technology_path = fixtures / "emir/ics55_synthetic.tech"
    override = {"technology_file_path": str(technology_path)}
    workspace = create_workspace(
        directory=tmp_path / "workspace",
        origin_def="",
        origin_verilog=fixtures / "gcd/gcd.v",
        pdk="ics55",
        pdk_root=str(minimal_ics55_pdk_factory(tmp_path / "pdk")),
        parameters={"config_overrides": {"emir": override}},
    )
    config_path = workspace.config[StepEnum.EMIR.value]
    assert json_read(config_path) == override

    assert json_write(config_path, {"technology_file_path": "stale-path.tech"})
    refresh_workspace_config(workspace)

    assert json_read(config_path) == override


@pytest.fixture
def emir_case(tmp_path, monkeypatch):
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="gcd", top_module="gcd"))
    workspace.config = build_workspace_config_paths(workspace)
    workspace.config["dir"].mkdir()
    template = Path(builder.__file__).parent / "configs" / "emir_ecc.json"
    config = json_read(template)
    config["technology_file_path"] = str(tmp_path / "process.tech")
    assert json_write(workspace.config[StepEnum.EMIR.value], config)
    step = builder.build_step(
        workspace,
        StepEnum.EMIR.value,
        input_def=tmp_path / "powerAnalysis_ecc" / "output" / "gcd_powerAnalysis.def.gz",
        input_verilog=tmp_path / "powerAnalysis_ecc" / "output" / "gcd_powerAnalysis.v.gz",
    )
    builder.build_step_space(step)
    module = Mock(spec=ECCToolsModule)
    module.init_emir.return_value = True
    module.run_emir.return_value = True
    save_data = Mock(return_value=True)
    monkeypatch.setattr(runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(runner, "save_data", save_data)
    return workspace, step, module, save_data


def write_native_emir_reports(step, *files: str) -> None:
    reporter_dir = step.data.steps[StepEnum.EMIR.value] / "emir_reporter"
    for relative_path in files:
        report_path = reporter_dir / relative_path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(relative_path)


def test_emir_dispatch_loads_ipw_power_and_preserves_downstream_outputs(emir_case):
    workspace, step, module, save_data = emir_case
    write_native_emir_reports(step, "ir.rpt")

    assert runner.run_step(workspace, step, module) is True

    assert module.method_calls == [
        call.update_step_paths(output_dir=step.data.dir, feature_dir=step.feature.dir),
        call.init_emir(
            output_dir=workspace.directory / "emir_ecc" / "data" / "emir",
            instance_power_file_path=(
                workspace.directory
                / "powerAnalysis_ecc"
                / "data"
                / "pw"
                / "power_reporter"
                / "instance_power.tsv"
            ),
            technology_file_path=str(workspace.directory / "process.tech"),
            ploc_file_path=(
                workspace.directory
                / "postFloorplan_ecc"
                / "data"
                / "fp"
                / "pdn_generator"
                / "power.ploc"
            ),
        ),
        call.run_emir(),
        call.destroy_emir(),
    ]
    save_data.assert_called_once_with(
        workspace=workspace, step=step, ecc_module=module, feature_step=False
    )
    persisted = json_read(step.subflow.path)
    assert [(item["name"], item["state"]) for item in persisted["steps"]] == [
        ("load data", "Success"),
        ("run EMIR", "Success"),
        ("save data", "Success"),
    ]


def test_emir_placeholder_does_not_run_native_analysis(emir_case):
    workspace, step, module, save_data = emir_case
    template = Path(builder.__file__).parent / "configs" / "emir_ecc.json"
    assert json_write(workspace.config[StepEnum.EMIR.value], json_read(template))

    assert runner.run_step(workspace, step, module) is False

    assert module.method_calls == []
    save_data.assert_not_called()
    assert [(item["name"], item["state"]) for item in step.subflow.steps] == [
        ("load data", "Unstart"),
        ("run EMIR", "Incomplete"),
        ("save data", "Unstart"),
    ]


@pytest.mark.parametrize("failed_method", ["init_emir", "run_emir"])
def test_emir_native_failure_releases_resources_without_saving(emir_case, failed_method):
    workspace, step, module, save_data = emir_case
    getattr(module, failed_method).return_value = False

    assert runner.run_step(workspace, step, module) is False

    assert module.destroy_emir.call_count == (failed_method == "run_emir")
    assert module.run_emir.call_count == (failed_method == "run_emir")
    save_data.assert_not_called()
    assert [(item["name"], item["state"]) for item in step.subflow.steps] == [
        ("load data", "Success"),
        ("run EMIR", "Incomplete"),
        ("save data", "Unstart"),
    ]


@pytest.mark.parametrize("failed_method", ["init_emir", "run_emir"])
def test_emir_exception_releases_resources_and_marks_failure(emir_case, failed_method):
    workspace, step, module, save_data = emir_case
    getattr(module, failed_method).side_effect = RuntimeError("native failure")

    with pytest.raises(RuntimeError, match="native failure"):
        runner.run_step(workspace, step, module)

    assert module.destroy_emir.call_count == (failed_method == "run_emir")
    save_data.assert_not_called()
    assert [(item["name"], item["state"]) for item in step.subflow.steps] == [
        ("load data", "Success"),
        ("run EMIR", "Incomplete"),
        ("save data", "Unstart"),
    ]


def test_emir_save_failure_is_not_success(emir_case):
    workspace, step, module, save_data = emir_case
    save_data.return_value = False

    assert runner.run_step(workspace, step, module) is False

    assert [(item["name"], item["state"]) for item in step.subflow.steps] == [
        ("load data", "Success"),
        ("run EMIR", "Success"),
        ("save data", "Incomplete"),
    ]


def test_emir_publishes_native_reports_after_save(emir_case):
    workspace, step, _module, _save_data = emir_case
    write_native_emir_reports(step, "ir.rpt", "gcd.em.worst", "nested/res_network.rpt")

    assert runner.run_step(workspace, step, _module) is True

    assert (step.report.dir / "ir.rpt").read_text() == "ir.rpt"
    assert (step.report.dir / "gcd.em.worst").read_text() == "gcd.em.worst"
    assert (step.report.dir / "nested" / "res_network.rpt").read_text() == "nested/res_network.rpt"
    assert [(item["name"], item["state"]) for item in step.subflow.steps] == [
        ("load data", "Success"),
        ("run EMIR", "Success"),
        ("save data", "Success"),
    ]


def test_emir_missing_native_reports_does_not_change_save_result(emir_case):
    workspace, step, _module, _save_data = emir_case

    assert runner.run_step(workspace, step, _module) is True

    assert [(item["name"], item["state"]) for item in step.subflow.steps] == [
        ("load data", "Success"),
        ("run EMIR", "Success"),
        ("save data", "Success"),
    ]


def test_emir_wrapper_forwards_paths_and_uses_ifp_supply_file(tmp_path):
    module = ECCToolsModule.__new__(ECCToolsModule)
    module.ecc = Mock()
    module.ecc.init_emir.return_value = True
    module.ecc.run_emir.return_value = True
    module.ecc.destroy_emir.return_value = True

    assert (
        module.init_emir(
            tmp_path / "emir",
            tmp_path / "instance_power.tsv",
            tmp_path / "process.tech",
            tmp_path / "power.ploc",
        )
        is True
    )
    assert module.run_emir() is True
    assert module.destroy_emir() is True

    assert module.ecc.method_calls == [
        call.init_emir(
            temp_directory_path=tmp_path / "emir",
            instance_power_file_path=tmp_path / "instance_power.tsv",
            technology_file_path=tmp_path / "process.tech",
            ploc_file_path=tmp_path / "power.ploc",
        ),
        call.run_emir(),
        call.destroy_emir(),
    ]
