from chipcompiler.data import OriginDesign, StepEnum, Workspace, WorkspaceStep
from chipcompiler.tools.ecc_dreamplace.module import DreamplaceModule
from chipcompiler.utility import json_write


class FakeParams:
    def fromJson(self, config):
        self.__dict__.update(config)


def test_build_params_preserves_routability_config_and_forces_timing_off(tmp_path):
    config_path = tmp_path / "dreamplace.json"
    json_write(
        str(config_path),
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
        config={"dreamplace": str(config_path)},
    )
    result_dir = tmp_path / "data" / "pl"
    step = WorkspaceStep(
        name=StepEnum.PLACEMENT.value,
        data={"dir": str(tmp_path / "data"), StepEnum.PLACEMENT.value: str(result_dir)},
    )
    module = DreamplaceModule(
        workspace=workspace,
        step=step,
        ecc_module=None,
        input_def="input.def",
        input_verilog="input.v",
        output_def="output.def",
        output_verilog="output.v",
    )

    params = module._build_params(FakeParams, legalize_only=False)

    assert params.routability_opt_flag == 1
    assert params.get_congestion_map == 1
    assert params.with_sta is False
    assert params.timing_opt_flag == 0
    assert params.timing_eval_flag == 0
    assert params.differentiable_timing_obj == 0
    assert params.def_input == "input.def"
    assert params.verilog_input == "input.v"
    assert params.result_dir == str(result_dir)
    assert params.base_design_name == "gcd"
