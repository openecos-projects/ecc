from pathlib import Path
from types import SimpleNamespace

from chipcompiler.data import EccData, EccStep, LogPaths, OriginDesign, StepEnum, Workspace
from chipcompiler.tools.ecc_dreamplace.module import DreamplaceModule
from chipcompiler.tools.ecc_dreamplace.service import get_step_info
from chipcompiler.utility import json_write


class FakeParams:
    def fromJson(self, config):
        self.__dict__.update(config)


def test_build_params_preserves_routability_config_and_forces_timing_off(tmp_path):
    config_path = tmp_path / "dreamplace_ecc.json"
    json_write(
        config_path,
        {
            "routability_opt_flag": 1,
            "get_congestion_map": 1,
            "with_sta": True,
            "timing_opt_flag": 1,
            "timing_eval_flag": 1,
            "differentiable_timing_obj": 1,
        },
    )
    workspace = Workspace(
        directory=str(tmp_path / "workspace"),
        design=OriginDesign(name="gcd"),
        config={"dreamplace": config_path},
    )
    result_dir = tmp_path / "data" / "pl"
    step_data = EccData(dir=tmp_path / "data", steps={StepEnum.PLACEMENT.value: result_dir})
    step = EccStep(
        name=StepEnum.PLACEMENT.value,
        data=step_data,
    )
    module = DreamplaceModule(
        workspace=workspace,
        step=step,
        ecc_module=None,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
        output_def=tmp_path / "output.def",
        output_verilog=tmp_path / "output.v",
    )

    params = module._build_params(FakeParams, legalize_only=False)

    assert params.routability_opt_flag == 1
    assert params.get_congestion_map == 1
    assert params.with_sta is False
    assert params.timing_opt_flag == 0
    assert params.timing_eval_flag == 0
    assert params.differentiable_timing_obj == 0
    assert params.def_input == str(tmp_path / "input.def")
    assert params.verilog_input == str(tmp_path / "input.v")
    assert params.result_dir == str(result_dir)
    assert params.base_design_name == "gcd"


def test_build_params_uses_empty_strings_for_missing_inputs(tmp_path):
    config_path = tmp_path / "dreamplace_ecc.json"
    json_write(config_path, {})
    workspace = Workspace(
        directory=str(tmp_path / "workspace"),
        design=OriginDesign(name="gcd"),
        config={"dreamplace": config_path},
    )
    result_dir = tmp_path / "data" / "pl"
    step_data = EccData(dir=tmp_path / "data", steps={StepEnum.PLACEMENT.value: result_dir})
    step = EccStep(
        name=StepEnum.PLACEMENT.value,
        data=step_data,
    )
    module = DreamplaceModule(
        workspace=workspace,
        step=step,
        ecc_module=None,
        input_def=None,
        input_verilog=None,
        output_def=tmp_path / "output.def",
        output_verilog=tmp_path / "output.v",
    )

    params = module._build_params(FakeParams, legalize_only=False)

    assert params.def_input == ""
    assert params.verilog_input == ""


def test_dreamplace_step_info_stringifies_path_config(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd"),
        config={"dreamplace": tmp_path / "config" / "dreamplace_ecc.json"},
    )
    workspace.logger = SimpleNamespace(
        log_section=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
    )
    step = EccStep(name=StepEnum.PLACEMENT.value)

    assert get_step_info(workspace, step, "config") == {
        "config": str(workspace.config["dreamplace"]),
    }


def _module_for_owner(tmp_path, step_name: str) -> DreamplaceModule:
    config_path = tmp_path / "dreamplace_ecc.json"
    json_write(config_path, {})
    workspace = Workspace(
        directory=str(tmp_path / "workspace"),
        design=OriginDesign(name="gcd"),
        config={"dreamplace": config_path},
    )
    result_dir = tmp_path / "data" / "to"
    step = EccStep(
        name=step_name,
        data=EccData(dir=tmp_path / "data", steps={step_name: result_dir}),
        log=LogPaths(file=tmp_path / "step.log"),
    )
    return DreamplaceModule(
        workspace=workspace,
        step=step,
        ecc_module=None,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
        output_def=tmp_path / "output.def",
        output_verilog=tmp_path / "output.v",
    )


def test_run_legalization_allows_timing_opt_and_legalization_owners(tmp_path, monkeypatch):
    seen: list[str] = []

    def fake_run(self, *, legalize_only: bool) -> bool:
        seen.append(self.step.name)
        assert legalize_only is True
        return True

    monkeypatch.setattr(DreamplaceModule, "_run", fake_run)

    legalization = _module_for_owner(tmp_path, StepEnum.LEGALIZATION.value)
    timing_opt = _module_for_owner(tmp_path, StepEnum.TIMING_OPT.value)
    placement = _module_for_owner(tmp_path, StepEnum.PLACEMENT.value)

    assert legalization.run_legalization() is True
    assert timing_opt.run_legalization() is True
    assert placement.run_legalization() is False
    assert seen == [StepEnum.LEGALIZATION.value, StepEnum.TIMING_OPT.value]


def test_timing_opt_legalize_log_does_not_reuse_step_log(tmp_path):
    legalization = _module_for_owner(tmp_path, StepEnum.LEGALIZATION.value)
    timing_opt = _module_for_owner(tmp_path, StepEnum.TIMING_OPT.value)

    assert legalization._file_handler_path(legalize_only=True) == str(tmp_path / "step.log")
    assert timing_opt._file_handler_path(legalize_only=True) == str(
        Path(timing_opt.result_dir) / "dreamplace_legalization.log"
    )


def test_dreamplace_run_step_ignores_timing_opt(tmp_path, monkeypatch):
    from chipcompiler.tools.ecc_dreamplace import runner as dreamplace_runner

    monkeypatch.setattr(dreamplace_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(dreamplace_runner, "run_placement", lambda **kwargs: True)
    monkeypatch.setattr(dreamplace_runner, "run_legalization", lambda **kwargs: True)

    workspace = Workspace(directory=str(tmp_path / "workspace"), design=OriginDesign(name="gcd"))
    step = EccStep(name=StepEnum.TIMING_OPT.value)

    assert dreamplace_runner.run_step(workspace, step) is False


def test_legalize_layout_rebuilds_from_sources_and_closes_on_failure(tmp_path, monkeypatch):
    from chipcompiler.tools.ecc_dreamplace import runner as dreamplace_runner
    from chipcompiler.tools.ecc_dreamplace.module import DreamplaceModule

    module = _module_for_owner(tmp_path, StepEnum.TIMING_OPT.value)
    staging_def = tmp_path / "sizer.def.gz"
    staging_verilog = tmp_path / "sizer.v.gz"
    created = []
    closed = []

    class LocalEcc:
        def close(self):
            closed.append(True)

    def fake_create_db_engine(workspace, load_step):
        created.append(
            (
                load_step.input.def_,
                load_step.input.verilog,
                load_step.input.db,
                load_step.name,
                workspace,
            )
        )
        return LocalEcc()

    monkeypatch.setattr(dreamplace_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(dreamplace_runner.ecc_runner, "create_db_engine", fake_create_db_engine)
    monkeypatch.setattr(DreamplaceModule, "run_legalization", lambda self: False)

    assert (
        dreamplace_runner.legalize_layout(
            module.workspace,
            module.step,
            staging_def,
            staging_verilog,
        )
        is None
    )
    assert created == [
        (staging_def, staging_verilog, None, StepEnum.TIMING_OPT.value, module.workspace)
    ]
    assert closed == [True]


def test_legalize_layout_returns_none_without_dreamplace_config(tmp_path, monkeypatch):
    from chipcompiler.tools.ecc_dreamplace import runner as dreamplace_runner

    workspace = Workspace(directory=str(tmp_path / "workspace"), design=OriginDesign(name="gcd"))
    step = EccStep(name=StepEnum.TIMING_OPT.value)
    monkeypatch.setattr(dreamplace_runner, "is_eda_exist", lambda: True)

    assert (
        dreamplace_runner.legalize_layout(
            workspace,
            step,
            tmp_path / "sizer.def.gz",
            tmp_path / "sizer.v.gz",
        )
        is None
    )


def test_legalize_layout_fills_missing_dreamplace_config_without_clobbering(tmp_path, monkeypatch):
    from chipcompiler.tools.ecc_dreamplace import runner as dreamplace_runner
    from chipcompiler.tools.ecc_dreamplace.module import DreamplaceModule

    workspace_dir = tmp_path / "workspace"
    config_path = workspace_dir / "config" / "dreamplace_ecc.json"
    config_path.parent.mkdir(parents=True)
    json_write(config_path, {})
    workspace = Workspace(
        directory=str(workspace_dir),
        design=OriginDesign(name="gcd"),
        config={"db": workspace_dir / "config" / "db_ecc.json"},
    )
    step = EccStep(
        name=StepEnum.TIMING_OPT.value,
        data=EccData(
            dir=tmp_path / "data",
            steps={StepEnum.TIMING_OPT.value: tmp_path / "data" / "to"},
        ),
        log=LogPaths(file=tmp_path / "step.log"),
    )
    engine = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(dreamplace_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(
        dreamplace_runner.ecc_runner,
        "create_db_engine",
        lambda *args, **kwargs: engine,
    )
    monkeypatch.setattr(DreamplaceModule, "run_legalization", lambda self: True)

    assert (
        dreamplace_runner.legalize_layout(
            workspace,
            step,
            tmp_path / "sizer.def.gz",
            tmp_path / "sizer.v.gz",
        )
        is engine
    )
    assert workspace.config["db"] == workspace_dir / "config" / "db_ecc.json"
    assert workspace.config["dreamplace"] == config_path


def test_legalize_layout_returns_engine_when_legalize_succeeds(tmp_path, monkeypatch):
    from chipcompiler.tools.ecc_dreamplace import runner as dreamplace_runner
    from chipcompiler.tools.ecc_dreamplace.module import DreamplaceModule

    module = _module_for_owner(tmp_path, StepEnum.TIMING_OPT.value)
    engine = SimpleNamespace(close=lambda: (_ for _ in ()).throw(AssertionError("closed")))

    monkeypatch.setattr(dreamplace_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(
        dreamplace_runner.ecc_runner,
        "create_db_engine",
        lambda *args, **kwargs: engine,
    )
    monkeypatch.setattr(DreamplaceModule, "run_legalization", lambda self: True)

    assert (
        dreamplace_runner.legalize_layout(
            module.workspace,
            module.step,
            tmp_path / "sizer.def.gz",
            tmp_path / "sizer.v.gz",
        )
        is engine
    )
