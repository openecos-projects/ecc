from pathlib import Path

import pytest

from chipcompiler.data import (
    EccData,
    EccStep,
    OriginDesign,
    StepEnum,
    Workspace,
)
from chipcompiler.tools.ecc_dreamplace.module import DreamplaceModule, DreamplaceRunMode
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
        (DreamplaceRunMode.PLACEMENT, {"status": "ok"}, True),
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
                StepEnum.MACRO_PLACEMENT.value: tmp_path / "data" / "macro",
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


def test_build_params_preserves_placement_timing_config(tmp_path):
    config_path = tmp_path / "dreamplace_ecc.json"
    json_write(
        config_path,
        {
            "random_seed": 17,
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
    assert params.random_seed == 17
    assert params.get_congestion_map == 1
    assert params.macro_only == 0
    assert params.with_sta is True
    assert params.timing_opt_flag == 1
    assert params.timing_eval_flag == 1
    assert params.differentiable_timing_obj == 1
    assert params.def_input == str(tmp_path / "input.def")
    assert params.verilog_input == str(tmp_path / "input.v")
    assert params.result_dir == str(result_dir)
    assert params.base_design_name == "gcd"


def test_build_params_diff_sizing_uses_standalone_s50_profile(tmp_path, dreamplace_default_config):
    config_path = tmp_path / "dreamplace_ecc.json"
    inherited = dict(
        dreamplace_default_config,
        auto_adjust_bins=1,
        num_bins_x=64,
        num_bins_y=64,
        route_num_bins_x=128,
        route_num_bins_y=128,
        timing_wns_coeff=2.5,
        timing_tns_coeff=0.025,
        timing_grad_balance_weight=7.0,
        timing_slew_weight=3.0,
        timing_cap_weight=4.0,
        overflow_reference_mode="ordinary",
    )
    json_write(config_path, inherited)
    workspace = Workspace(
        directory=tmp_path / "workspace",
        design=OriginDesign(name="gcd"),
        config={"dreamplace": config_path},
    )
    result_dir = tmp_path / "data" / "diff_sizing"
    step = EccStep(
        name=StepEnum.DIFF_SIZING.value,
        data=EccData(dir=tmp_path / "data", steps={StepEnum.DIFF_SIZING.value: result_dir}),
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

    params = module._build_params(FakeParams, mode=DreamplaceRunMode.DIFF_SIZING)

    assert {
        "flow_kind": params.flow_kind,
        "timing_rc_mode": params.timing_rc_mode,
        "placement_sizing_mode": params.placement_sizing_mode,
        "sizing_parameterization": params.sizing_parameterization,
        "real_size_execution_mode": params.real_size_execution_mode,
        "real_size_warmup_steps": params.real_size_warmup_steps,
        "diff_sizing_continuous_steps": params.diff_sizing_continuous_steps,
        "timing_wns_coeff": params.timing_wns_coeff,
        "timing_tns_coeff": params.timing_tns_coeff,
        "timing_slew_weight": params.timing_slew_weight,
        "timing_cap_weight": params.timing_cap_weight,
        "timing_grad_balance_weight": params.timing_grad_balance_weight,
        "target_density": params.target_density,
        "cell_padding_x": params.cell_padding_x,
        "overflow_reference_mode": params.overflow_reference_mode,
        "gpugr_backend": params.gpugr_backend,
        "gr_sizing_rrr_iters": params.gr_sizing_rrr_iters,
        "auto_adjust_bins": params.auto_adjust_bins,
        "num_bins_x": params.num_bins_x,
        "num_bins_y": params.num_bins_y,
        "route_num_bins_x": params.route_num_bins_x,
        "route_num_bins_y": params.route_num_bins_y,
        "timing_opt_enabled": params.timing_opt_enabled,
        "timing_opt_flag": params.timing_opt_flag,
        "timing_eval_flag": params.timing_eval_flag,
        "routability_opt_flag": params.routability_opt_flag,
        "with_sta": params.with_sta,
        "timing_objective_lane": params.timing_objective_lane,
    } == {
        "flow_kind": "sizing",
        "timing_rc_mode": "gr",
        "placement_sizing_mode": "size_only",
        "sizing_parameterization": "logits",
        "real_size_execution_mode": "continuous_only",
        "real_size_warmup_steps": 0,
        "diff_sizing_continuous_steps": 0,
        "timing_wns_coeff": dreamplace_default_config["diff_sizing_coefficients"]["wns"],
        "timing_tns_coeff": dreamplace_default_config["diff_sizing_coefficients"]["tns"],
        "timing_slew_weight": dreamplace_default_config["diff_sizing_coefficients"]["slew"],
        "timing_cap_weight": dreamplace_default_config["diff_sizing_coefficients"]["cap"],
        "timing_grad_balance_weight": 1.0,
        "target_density": 0.4,
        "cell_padding_x": 0,
        "overflow_reference_mode": "ordinary",
        "gpugr_backend": "cpu_pr_maze",
        "gr_sizing_rrr_iters": 3,
        "auto_adjust_bins": 0,
        "num_bins_x": 512,
        "num_bins_y": 512,
        "route_num_bins_x": 512,
        "route_num_bins_y": 512,
        "timing_opt_enabled": 0,
        "timing_opt_flag": 0,
        "timing_eval_flag": 1,
        "routability_opt_flag": 0,
        "with_sta": 1,
        "timing_objective_lane": "timing_slew_cap",
    }
    assert {
        key: params.global_place_stages[0][key]
        for key in ("num_bins_x", "num_bins_y", "iteration", "optimizer")
    } == {"num_bins_x": 512, "num_bins_y": 512, "iteration": 50, "optimizer": "adam"}
    assert params.design_inputs["rcx_config"] == ""


def test_build_params_resolves_openroad_timing_inputs(tmp_path):
    pdk_root = tmp_path / "pdk"
    pdk_root.mkdir()
    rc_tcl = pdk_root / "setRC.tcl"
    rc_tcl.write_text("set_wire_rc -signal -layer MET3\n", encoding="utf-8")
    config_path = tmp_path / "dreamplace_ecc.json"
    json_write(
        config_path,
        {
            "flow_kind": "placement",
            "place_io_engine": "openroad",
            "rc_tcl": "setRC.tcl",
            "diff_timing_driven_placement": 1,
        },
    )
    workspace = Workspace(
        directory=tmp_path / "workspace",
        design=OriginDesign(name="gcd"),
        config={"dreamplace": config_path},
    )
    workspace.pdk.root = pdk_root
    workspace.pdk.tech = pdk_root / "tech.lef"
    workspace.pdk.lefs = [pdk_root / "cells.lef"]
    workspace.pdk.libs = [pdk_root / "cells.lib"]
    workspace.pdk.sdc = tmp_path / "gcd.sdc"
    result_dir = tmp_path / "data" / "pl"
    step = EccStep(
        name=StepEnum.PLACEMENT.value,
        data=EccData(dir=tmp_path / "data", steps={StepEnum.PLACEMENT.value: result_dir}),
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

    assert params.flow_kind == "placement"
    assert params.diff_timing_driven_placement == 1
    assert params.with_sta == 1
    assert params.timing_topology_refresh_interval == 15
    assert params.timing_topology_enable_overflow_threshold == 0.35
    assert params.design_inputs == {
        "tech_lef": str(pdk_root / "tech.lef"),
        "lef": [str(pdk_root / "cells.lef")],
        "lib": [str(pdk_root / "cells.lib")],
        "def": str(tmp_path / "input.def"),
        "verilog": str(tmp_path / "input.v"),
        "sdc": str(tmp_path / "gcd.sdc"),
        "rc_tcl": str(rc_tcl),
    }


def test_build_params_accepts_ecc_geometry_only_placement(tmp_path):
    config_path = tmp_path / "dreamplace_ecc.json"
    json_write(config_path, {"place_io_engine": "ecc"})
    workspace = Workspace(
        directory=tmp_path / "workspace",
        design=OriginDesign(name="gcd"),
        config={"dreamplace": config_path},
    )
    step = EccStep(
        name=StepEnum.PLACEMENT.value,
        data=EccData(
            dir=tmp_path / "data",
            steps={StepEnum.PLACEMENT.value: tmp_path / "data" / "pl"},
        ),
    )
    module = DreamplaceModule(
        workspace=workspace,
        step=step,
        ecc_module=object(),
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
        output_def=tmp_path / "output.def",
        output_verilog=None,
    )

    params = module._build_params(FakeParams, mode=DreamplaceRunMode.PLACEMENT)

    assert params.place_io_engine == "ecc"
    assert not hasattr(params, "design_inputs")


def test_build_params_resolves_ecc_timing_inputs(tmp_path):
    config_path = tmp_path / "dreamplace_ecc.json"
    json_write(
        config_path,
        {"place_io_engine": "ecc", "with_sta": 1},
    )
    workspace = Workspace(
        directory=tmp_path / "workspace",
        design=OriginDesign(name="gcd"),
        config={"dreamplace": config_path},
    )
    step = EccStep(name=StepEnum.PLACEMENT.value, data=EccData(dir=tmp_path / "data"))
    module = DreamplaceModule(
        workspace=workspace,
        step=step,
        ecc_module=object(),
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
        output_def=tmp_path / "output.def",
        output_verilog=None,
    )

    params = module._build_params(FakeParams, mode=DreamplaceRunMode.PLACEMENT)

    assert params.place_io_engine == "ecc"
    assert params.with_sta == 1
    assert params.design_inputs["def"] == str(tmp_path / "input.def")
    assert params.design_inputs["verilog"] == str(tmp_path / "input.v")
    assert "lib" in params.design_inputs
    assert "sdc" in params.design_inputs
    assert Path(params.design_inputs["work_dir"]).parent == Path(module.result_dir)


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
        name=StepEnum.MACRO_PLACEMENT.value,
        data=EccData(
            dir=tmp_path / "data",
            steps={StepEnum.MACRO_PLACEMENT.value: tmp_path / "data" / "macro"},
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
