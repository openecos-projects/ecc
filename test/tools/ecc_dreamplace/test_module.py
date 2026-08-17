from types import SimpleNamespace

from chipcompiler.data import EccData, EccStep, OriginDesign, StepEnum, Workspace
from chipcompiler.tools.ecc_dreamplace.module import DreamplaceModule
from chipcompiler.tools.ecc_dreamplace.service import get_step_info
from chipcompiler.utility import json_write


class FakeParams:
    def fromJson(self, config):
        self.__dict__.update(config)


def test_build_params_preserves_routability_config_and_forces_timing_off(tmp_path):
    config_path = tmp_path / "dreamplace.json"
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
    config_path = tmp_path / "dreamplace.json"
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
        config={"dreamplace": tmp_path / "config" / "dreamplace.json"},
    )
    workspace.logger = SimpleNamespace(
        log_section=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
    )
    step = EccStep(name=StepEnum.PLACEMENT.value)

    assert get_step_info(workspace, step, "config") == {
        "config": str(workspace.config["dreamplace"]),
    }


def test_run_binds_ecc_backend_instead_of_raw_db(tmp_path, monkeypatch):
    import sys
    import types

    config_path = tmp_path / "dreamplace.json"
    json_write(config_path, {"route_num_bins_x": 8, "route_num_bins_y": 8})
    workspace = Workspace(
        directory=str(tmp_path / "workspace"),
        design=OriginDesign(name="gcd"),
        config={"dreamplace": config_path},
    )
    result_dir = tmp_path / "data" / "pl"
    result_dir.mkdir(parents=True)
    step_data = EccData(dir=tmp_path / "data", steps={StepEnum.PLACEMENT.value: result_dir})
    step = EccStep(name=StepEnum.PLACEMENT.value, data=step_data)
    backend = SimpleNamespace()
    module = DreamplaceModule(
        workspace=workspace,
        step=step,
        ecc_module=backend,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
        output_def=tmp_path / "output.def",
        output_verilog=tmp_path / "output.v",
    )

    bound = {}

    class FakeEngine:
        def __init__(self, params):
            bound["params"] = params

        def bind_backend(self, ecc_backend):
            bound["backend"] = ecc_backend

        def run(self):
            bound["ran"] = True
            return {"hpwl": 1.0}

    fake_params = types.ModuleType("dreamplace.Params")
    fake_params.Params = FakeParams
    fake_placer = types.ModuleType("dreamplace.Placer")
    fake_placer.PlacementEngine = FakeEngine
    fake_dreamplace = types.ModuleType("dreamplace")
    fake_dreamplace.Params = fake_params
    fake_dreamplace.Placer = fake_placer
    monkeypatch.setitem(sys.modules, "dreamplace", fake_dreamplace)
    monkeypatch.setitem(sys.modules, "dreamplace.Params", fake_params)
    monkeypatch.setitem(sys.modules, "dreamplace.Placer", fake_placer)

    assert module.run_placement() is True
    assert bound["backend"] is backend
    assert bound["ran"] is True
    assert not hasattr(FakeEngine, "setup_rawdb")
