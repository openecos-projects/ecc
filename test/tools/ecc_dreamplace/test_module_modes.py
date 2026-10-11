from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.data import (
    EccData,
    EccStep,
    LogPaths,
    OriginDesign,
    SkippableStepEnum,
    StepEnum,
    Workspace,
)
from chipcompiler.tools.ecc_dreamplace.module import DreamplaceModule, DreamplaceRunMode
from chipcompiler.tools.ecc_dreamplace.service import get_step_info
from chipcompiler.utility import json_write

from .test_module import FakeParams


@pytest.mark.parametrize(
    ("owner", "detailed_place_flag"),
    [
        (StepEnum.LEGALIZATION.value, 0),
        (SkippableStepEnum.TIMING_OPT.value, 1),
    ],
)
def test_legalization_params_follow_owner(tmp_path, owner, detailed_place_flag):
    config_path = tmp_path / "dreamplace_ecc.json"
    json_write(
        config_path,
        {
            "macro_only": 1,
            "cell_padding_x": 300,
            "detailed_place_flag": 0,
            "post_legalization_adaptive_padding_flag": 1,
        },
    )
    workspace = Workspace(
        directory=str(tmp_path / "workspace"),
        design=OriginDesign(name="gcd"),
        config={"dreamplace": config_path},
    )
    step = EccStep(
        name=owner,
        data=EccData(
            dir=tmp_path / "data",
            steps={owner: tmp_path / "data" / "pl"},
        ),
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

    params = module._build_params(FakeParams, mode=DreamplaceRunMode.LEGALIZATION)

    assert {
        "macro_only": params.macro_only,
        "detailed_place_flag": params.detailed_place_flag,
        "cell_padding_x": params.cell_padding_x,
        "post_legalization_adaptive_padding_flag": params.post_legalization_adaptive_padding_flag,
    } == {
        "macro_only": 0,
        "detailed_place_flag": detailed_place_flag,
        "cell_padding_x": 0,
        "post_legalization_adaptive_padding_flag": 0,
    }


@pytest.mark.parametrize(
    ("owner", "site_width", "expected_padding"),
    [
        (StepEnum.LEGALIZATION.value, 200, 0),
        (StepEnum.LEGALIZATION.value, 420, 0),
        (SkippableStepEnum.TIMING_OPT.value, 200, 0),
    ],
)
def test_geometry_legalization_clears_inherited_padding(
    tmp_path, monkeypatch, owner, site_width, expected_padding
):
    import dreamplace.Params as params_module
    import dreamplace.Placer as placer_module

    seen = []

    class FakeEngine:
        def __init__(self, params):
            self.params = params

        def setup_rawdb(self, **_kwargs):
            self.placedb = SimpleNamespace(pydb=SimpleNamespace(site_width=site_width))

        def write_back(self, path):
            Path(path).write_text("fixture")

        def write_verilog(self, path):
            Path(path).write_text("fixture")

        def run(self):
            seen.append((self.params.detailed_place_flag, self.params.cell_padding_x))
            return {"hpwl": 1.0}

    module = _module_for_owner(tmp_path, owner)
    module.ecc_module = SimpleNamespace(
        dir_workspace=str(tmp_path),
        verilog_save=lambda **kwargs: Path(kwargs["output_verilog"]).write_text("fixture"),
    )
    json_write(module.param_path, {"cell_padding_x": 999, "detailed_place_flag": 1})
    monkeypatch.setattr(params_module, "Params", FakeParams)
    monkeypatch.setattr(placer_module, "PlacementEngine", FakeEngine)

    assert module.run_legalization() is True
    assert seen == [(int(owner != StepEnum.LEGALIZATION.value), expected_padding)]


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


@pytest.mark.parametrize(
    ("mode", "step_name", "expected"),
    [
        (DreamplaceRunMode.PLACEMENT, StepEnum.PLACEMENT.value, 1),
        (DreamplaceRunMode.MACRO_PLACEMENT, StepEnum.MACRO_PLACEMENT.value, 0),
        (DreamplaceRunMode.LEGALIZATION, StepEnum.LEGALIZATION.value, 0),
        (DreamplaceRunMode.LEGALIZATION, SkippableStepEnum.TIMING_OPT.value, 1),
    ],
)
def test_detailed_place_default_respects_run_mode(
    tmp_path, dreamplace_default_config, mode, step_name, expected
):
    module = _module_for_owner(tmp_path, step_name)
    from dreamplace.flows.flow_config import resolve_flow_config

    config = resolve_flow_config(dreamplace_default_config, explicit_keys=())
    json_write(module.param_path, config)

    assert module._build_params(FakeParams, mode=mode).detailed_place_flag == expected


def test_placement_respects_explicit_detailed_place_disable(tmp_path, dreamplace_default_config):
    module = _module_for_owner(tmp_path, StepEnum.PLACEMENT.value)
    from dreamplace.flows.flow_config import resolve_flow_config

    config = resolve_flow_config(dreamplace_default_config, explicit_keys=())
    config["detailed_place_flag"] = 0
    json_write(module.param_path, config)

    assert (
        module._build_params(FakeParams, mode=DreamplaceRunMode.PLACEMENT).detailed_place_flag == 0
    )


def test_run_legalization_allows_timing_opt_and_legalization_owners(tmp_path, monkeypatch):
    seen: list[str] = []

    def fake_run(self, *, mode: DreamplaceRunMode) -> bool:
        seen.append(self.step.name)
        assert mode is DreamplaceRunMode.LEGALIZATION
        return True

    monkeypatch.setattr(DreamplaceModule, "_run", fake_run)

    legalization = _module_for_owner(tmp_path, StepEnum.LEGALIZATION.value)
    timing_opt = _module_for_owner(tmp_path, SkippableStepEnum.TIMING_OPT.value)
    placement = _module_for_owner(tmp_path, StepEnum.PLACEMENT.value)

    assert legalization.run_legalization() is True
    assert timing_opt.run_legalization() is True
    assert placement.run_legalization() is False
    assert seen == [StepEnum.LEGALIZATION.value, SkippableStepEnum.TIMING_OPT.value]


def test_timing_opt_legalize_log_does_not_reuse_step_log(tmp_path):
    legalization = _module_for_owner(tmp_path, StepEnum.LEGALIZATION.value)
    timing_opt = _module_for_owner(tmp_path, SkippableStepEnum.TIMING_OPT.value)

    assert legalization._file_handler_path(mode=DreamplaceRunMode.LEGALIZATION) == str(
        tmp_path / "step.log"
    )
    assert timing_opt._file_handler_path(mode=DreamplaceRunMode.LEGALIZATION) == str(
        Path(timing_opt.result_dir) / "dreamplace_legalization.log"
    )


def test_macro_placement_log_does_not_reuse_step_log(tmp_path):
    macro_placement = _module_for_owner(tmp_path, StepEnum.MACRO_PLACEMENT.value)

    assert macro_placement._file_handler_path(mode=DreamplaceRunMode.MACRO_PLACEMENT) == str(
        Path(macro_placement.result_dir) / "dreamplace_macro_placement.log"
    )


def test_dreamplace_run_step_ignores_timing_opt(tmp_path, monkeypatch):
    from chipcompiler.tools.ecc_dreamplace import runner as dreamplace_runner

    monkeypatch.setattr(dreamplace_runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(dreamplace_runner, "run_placement", lambda **kwargs: True)
    monkeypatch.setattr(dreamplace_runner, "run_legalization", lambda **kwargs: True)

    workspace = Workspace(directory=str(tmp_path / "workspace"), design=OriginDesign(name="gcd"))
    step = EccStep(name=SkippableStepEnum.TIMING_OPT.value)

    assert dreamplace_runner.run_step(workspace, step) is False


def test_legalize_layout_rebuilds_from_sources_and_closes_on_failure(tmp_path, monkeypatch):
    from chipcompiler.tools.ecc_dreamplace import runner as dreamplace_runner
    from chipcompiler.tools.ecc_dreamplace.module import DreamplaceModule

    module = _module_for_owner(tmp_path, SkippableStepEnum.TIMING_OPT.value)
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
        (staging_def, staging_verilog, None, SkippableStepEnum.TIMING_OPT.value, module.workspace)
    ]
    assert closed == [True]


def test_legalize_layout_returns_none_without_dreamplace_config(tmp_path, monkeypatch):
    from chipcompiler.tools.ecc_dreamplace import runner as dreamplace_runner

    workspace = Workspace(directory=str(tmp_path / "workspace"), design=OriginDesign(name="gcd"))
    step = EccStep(name=SkippableStepEnum.TIMING_OPT.value)
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
        name=SkippableStepEnum.TIMING_OPT.value,
        data=EccData(
            dir=tmp_path / "data",
            steps={SkippableStepEnum.TIMING_OPT.value: tmp_path / "data" / "to"},
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

    module = _module_for_owner(tmp_path, SkippableStepEnum.TIMING_OPT.value)
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
