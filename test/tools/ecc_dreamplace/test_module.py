from types import SimpleNamespace

import pytest

from chipcompiler.data import EccData, EccStep, OriginDesign, StepEnum, Workspace
from chipcompiler.tools.ecc.subflow import EccSubFlow
from chipcompiler.tools.ecc_dreamplace import builder as dreamplace_builder
from chipcompiler.tools.ecc_dreamplace.module import DreamplaceModule, DreamplaceRunMode
from chipcompiler.tools.ecc_dreamplace.service import get_step_info
from chipcompiler.utility import json_write


class FakeParams:
    def fromJson(self, config):
        self.__dict__.update(config)


@pytest.mark.parametrize(
    ("mode", "result", "expected"),
    [
        (
            DreamplaceRunMode.MACRO_PLACEMENT,
            {
                "executed": False,
                "candidate_count": 0,
                "reason": "no_unplaced_hard_macros",
            },
            True,
        ),
        (DreamplaceRunMode.MACRO_PLACEMENT, {"executed": False}, False),
        (DreamplaceRunMode.PLACEMENT, {}, False),
        (DreamplaceRunMode.PLACEMENT, {"hpwl": 1.0}, True),
    ],
)
def test_run_accepts_only_the_defined_empty_macro_short_circuit(
    monkeypatch, tmp_path, mode, result, expected
):
    import dreamplace.Params as params_module
    import dreamplace.Placer as placer_module

    class FakeEngine:
        def __init__(self, _params):
            pass

        def setup_rawdb(self, **_kwargs):
            pass

        def run(self):
            return result

    config_path = tmp_path / "dreamplace_ecc.json"
    json_write(config_path, {})
    workspace = Workspace(
        directory=tmp_path / "workspace",
        design=OriginDesign(name="gcd"),
        config={"dreamplace": config_path},
    )
    step = EccStep(
        name=(
            StepEnum.MACRO_PLACEMENT.value
            if mode is DreamplaceRunMode.MACRO_PLACEMENT
            else StepEnum.PLACEMENT.value
        ),
        data=EccData(
            dir=tmp_path / "data",
            steps={
                StepEnum.MACRO_PLACEMENT.value: tmp_path / "data" / "macro_pl",
                StepEnum.PLACEMENT.value: tmp_path / "data" / "pl",
            },
        ),
    )
    module = DreamplaceModule(
        workspace=workspace,
        step=step,
        ecc_module=object(),
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
        output_def=tmp_path / "output.def",
        output_verilog=tmp_path / "output.v",
    )
    monkeypatch.setattr(params_module, "Params", FakeParams)
    monkeypatch.setattr(placer_module, "PlacementEngine", FakeEngine)

    assert module._run(mode=mode) is expected


def test_build_params_preserves_routability_config_and_forces_timing_off(tmp_path):
    config_path = tmp_path / "dreamplace_ecc.json"
    json_write(
        config_path,
        {
            "macro_only": 1,
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

    params = module._build_params(FakeParams, mode=DreamplaceRunMode.PLACEMENT)

    assert params.routability_opt_flag == 1
    assert params.get_congestion_map == 1
    assert params.macro_only == 0
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

    params = module._build_params(FakeParams, mode=DreamplaceRunMode.PLACEMENT)

    assert params.def_input == ""
    assert params.verilog_input == ""


def test_macro_placement_forces_selective_non_routable_placement_params(tmp_path):
    config_path = tmp_path / "dreamplace_ecc.json"
    json_write(
        config_path,
        {
            "macro_only": 0,
            "global_place_flag": 0,
            "macro_place_flag": 0,
            "legalize_flag": 0,
            "two_stage_flag": 1,
            "routability_opt_flag": 1,
            "get_congestion_map": 1,
            "egr_padding_flag": 1,
        },
    )
    workspace = Workspace(
        directory=str(tmp_path / "workspace"),
        design=OriginDesign(name="gcd"),
        config={"dreamplace": config_path},
    )
    step = EccStep(
        name="macroPlacement",
        data=EccData(
            dir=tmp_path / "data", steps={"macroPlacement": tmp_path / "data" / "macro_pl"}
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

    params = module._build_params(FakeParams, mode=DreamplaceRunMode.MACRO_PLACEMENT)

    assert {
        "macro_only": params.macro_only,
        "global_place_flag": params.global_place_flag,
        "macro_place_flag": params.macro_place_flag,
        "legalize_flag": params.legalize_flag,
        "two_stage_flag": params.two_stage_flag,
        "macro_halo_x": params.macro_halo_x,
        "macro_halo_y": params.macro_halo_y,
        "routability_opt_flag": params.routability_opt_flag,
        "get_congestion_map": params.get_congestion_map,
        "egr_padding_flag": params.egr_padding_flag,
    } == {
        "macro_only": 1,
        "global_place_flag": 1,
        "macro_place_flag": 1,
        "legalize_flag": 1,
        "two_stage_flag": 0,
        "macro_halo_x": 2000,
        "macro_halo_y": 2000,
        "routability_opt_flag": 0,
        "get_congestion_map": 0,
        "egr_padding_flag": 0,
    }


def test_legalization_forces_macro_only_off(tmp_path):
    config_path = tmp_path / "dreamplace_ecc.json"
    json_write(config_path, {"macro_only": 1})
    workspace = Workspace(
        directory=str(tmp_path / "workspace"),
        design=OriginDesign(name="gcd"),
        config={"dreamplace": config_path},
    )
    step = EccStep(
        name=StepEnum.LEGALIZATION.value,
        data=EccData(
            dir=tmp_path / "data",
            steps={StepEnum.LEGALIZATION.value: tmp_path / "data" / "pl"},
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

    assert params.macro_only == 0


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


def test_macro_placement_step_has_complete_snapshot_and_dedicated_subflow(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd"),
    )
    step = dreamplace_builder.build_step(
        workspace=workspace,
        step_name=StepEnum.MACRO_PLACEMENT.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    dreamplace_builder.build_step_space(step)

    subflow = EccSubFlow(workspace=workspace, workspace_step=step)

    assert (
        step.output.def_ == tmp_path / "macroPlacement_dreamplace/output/gcd_macroPlacement.def.gz"
    )
    assert (
        step.output.verilog == tmp_path / "macroPlacement_dreamplace/output/gcd_macroPlacement.v.gz"
    )
    assert step.output.gds == tmp_path / "macroPlacement_dreamplace/output/gcd_macroPlacement.gds"
    assert step.output.db == tmp_path / "macroPlacement_dreamplace/output/gcd_macroPlacement_db"
    assert step.output.geometry_manifest == (
        tmp_path / "macroPlacement_dreamplace/output/geometry/geometry.manifest"
    )
    assert step.data.workdir_for(StepEnum.MACRO_PLACEMENT.value) == (
        tmp_path / "macroPlacement_dreamplace/data/macro_pl"
    )
    assert [item["name"] for item in subflow.workspace_step.subflow.steps] == [
        "load data",
        "run macro placement",
        "save data",
        "analysis",
    ]
