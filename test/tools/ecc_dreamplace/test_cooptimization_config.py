import json
import tomllib
from pathlib import Path

import pytest
import tomli_w

from chipcompiler.cli.project.params import (
    build_backend_overrides,
    build_config_overrides,
    parse_cli_overrides,
    parse_toml_params,
    resolve_parameters,
)
from chipcompiler.data import EccData, EccStep, OriginDesign, StepEnum, Workspace
from chipcompiler.data.workspace.config_overrides import apply_config_overrides
from chipcompiler.tools.ecc_dreamplace.module import DreamplaceModule, DreamplaceRunMode
from chipcompiler.tools.ecc_dreamplace.parameter_overrides import apply_direct_config_overrides

from .test_module import FakeParams


@pytest.mark.parametrize(
    "public",
    [
        {"place.timing_opt_enabled": 1},
        {"place.timing_opt_overflow_milestones": []},
        {"place.timing_opt_overflow_milestones": [0.6, 0.5, 0.4, 0.3, 0.2]},
        {"place.timing_opt_buffering_enabled": 0},
        {"place.timing_opt_buffering_enabled": 1},
        {"place.timing_opt_sizing_rounds": 5},
        {"place.timing_coeff_growth_factor": 1.0},
        {"place.timing_coeff_growth_factor": 1.02},
        {"place.timing_grad_balance_target_ratio": 0.2},
        {"place.timing_grad_balance_target_ratio": 0.0},
        {
            "place.timing_aggregation_mode": "smooth",
            "place.timing_aggregation_tau_ps": 10.0,
        },
        {
            "place.timing_aggregation_mode": "hard",
            "place.timing_aggregation_tau_ps": 0.5,
        },
        {"place.timing_opt_coefficients": {"mode": "inherit"}},
        {
            "place.timing_opt_coefficients": {
                "mode": "fixed",
                "wns": 500,
                "tns": 5,
                "slew": 1,
                "cap": 1,
            }
        },
        {"place.timing_placement_carrier": "pin2pin"},
        {"place.timing_placement_carrier": "direct_loss"},
    ],
)
def test_window_override_reaches_dreamplace_config(public, dreamplace_default_config):
    cli, errors = parse_cli_overrides(
        [
            key + "=" + (value if isinstance(value, str) else json.dumps(value))
            for key, value in public.items()
        ]
    )
    assert (cli, errors) == (public, [])
    direct = {key.removeprefix("place."): value for key, value in public.items()}
    toml, errors = parse_toml_params({"place": direct})
    assert (toml, errors) == (public, [])
    resolved, errors = resolve_parameters(cli_overrides=cli)
    assert errors == []
    overrides = build_config_overrides(resolved)
    actual = apply_direct_config_overrides(
        dreamplace_default_config, {"config_overrides": overrides}
    )
    assert actual == dreamplace_default_config | direct


def test_coefficient_mode_can_switch_without_removing_fixed_preset(dreamplace_default_config):
    from dreamplace.flows.flow_config import resolve_flow_config

    preset = {"mode": "fixed", "wns": 500.0, "tns": 5.0, "slew": 1.0, "cap": 1.0}
    config = dreamplace_default_config | {"timing_opt_coefficients": preset}
    for mode in ("inherit", "fixed"):
        cli, errors = parse_cli_overrides(
            [
                "place.timing_opt_coefficients=" + json.dumps({"mode": mode}),
            ]
        )
        assert errors == []
        resolved, errors = resolve_parameters(cli_overrides=cli)
        assert errors == []
        config = apply_direct_config_overrides(
            config,
            {"config_overrides": build_config_overrides(resolved)},
        )
        effective = resolve_flow_config(config, explicit_keys=("timing_opt_coefficients",))
        assert effective["timing_opt_coefficients"] == preset | {"mode": mode}


@pytest.mark.parametrize("enabled", [0, 1])
def test_legacy_timing_opt_override_is_accepted(dreamplace_default_config, enabled):
    public = {"place.inflation_s5b1_enabled": enabled}
    cli, errors = parse_cli_overrides([f"place.inflation_s5b1_enabled={enabled}"])
    assert (cli, errors) == (public, [])
    resolved, errors = resolve_parameters(cli_overrides=cli)
    assert errors == []
    overrides = build_config_overrides(resolved)
    actual = apply_direct_config_overrides(
        dreamplace_default_config, {"config_overrides": overrides}
    )
    assert actual == dreamplace_default_config | {"timing_opt_enabled": enabled}


def test_batch_profile_survives_public_params_and_geometry_mode_isolation(tmp_path):
    root = Path(__file__).resolve().parents[3]
    profile = json.loads((root / "test/regression/ics55/placement_s5b1.json").read_text())
    public = {key: value for key, value in profile.items() if value is not None}
    text = tomli_w.dumps({"params": {"place": public}})
    parsed, errors = parse_toml_params(tomllib.loads(text)["params"])
    assert errors == []
    resolved, errors = resolve_parameters(toml_overrides=parsed)
    assert errors == []
    parameters = build_backend_overrides(resolved)
    parameters["config_overrides"] = build_config_overrides(resolved)
    path = tmp_path / "dreamplace.json"
    baseline = root / "chipcompiler/tools/ecc_dreamplace/configs/dreamplace_ecc.json"
    path.write_text(baseline.read_text())
    apply_config_overrides({"dreamplace": path}, parameters)
    actual = json.loads(path.read_text())
    # Legacy shared parameters are consumed by the template factory itself.
    actual.update(parameters.get("dreamplace", {}))
    path.write_text(json.dumps(actual))
    assert {key: actual[key] for key in public} == public
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd"),
        config={"dreamplace": path},
    )
    step = EccStep(
        name=StepEnum.LEGALIZATION.value,
        data=EccData(steps={StepEnum.LEGALIZATION.value: tmp_path / "pl"}),
    )
    module = DreamplaceModule(workspace, step, None, None, None, None, None)
    params = module._build_params(FakeParams, mode=DreamplaceRunMode.LEGALIZATION)
    disabled = (
        "global_place_flag",
        "with_sta",
        "diff_timing_driven_placement",
        "differentiable_timing_obj",
        "timing_opt_enabled",
        "routability_opt_flag",
        "l_shape_routability_flag",
        "adjust_gpugr_area_flag",
        "gpugr_final_eval_flag",
        "joint_segment_virtual_density_enabled",
    )
    assert {key: getattr(params, key) for key in disabled} == dict.fromkeys(disabled, 0)
    assert params.place_io_engine == "ecc"
    import torch
    from dreamplace.NonLinearPlace import NonLinearPlace

    placer = object.__new__(NonLinearPlace)
    torch.nn.Module.__init__(placer)
    placer.size_params = torch.nn.ModuleDict()
    placer.vt_params = torch.nn.ModuleDict()
    placer._validate_sizing_mode(params)
