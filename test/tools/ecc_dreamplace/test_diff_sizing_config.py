"""Independent S50 coefficients through public overrides and step resolution."""

import json

import pytest

from chipcompiler.cli.project.params import (
    build_config_overrides,
    parse_cli_overrides,
    parse_toml_params,
    resolve_parameters,
)
from chipcompiler.data import PDK, OriginDesign, StepEnum, Workspace
from chipcompiler.data.workspace import init_workspace_config
from chipcompiler.tools.ecc_dreamplace import builder
from chipcompiler.tools.ecc_dreamplace.module import DreamplaceModule, DreamplaceRunMode
from chipcompiler.utility import json_read


@pytest.mark.parametrize(
    "override",
    [
        {},
        {"wns": 1000.0, "tns": 10.0, "cap": 0.5, "slew": 0.25},
        {"tns": 10.0},
    ],
)
def test_public_s50_coefficients_survive_step_resolution_without_changing_placement(
    tmp_path, monkeypatch, make_ics55_parameters, dreamplace_default_config, override
):
    from dreamplace.Params import Params

    public = {"place.diff_sizing_coefficients": override}
    cli, errors = parse_cli_overrides(["place.diff_sizing_coefficients=" + json.dumps(override)])
    assert (cli, errors) == (public, [])
    toml, errors = parse_toml_params({"place": {"diff_sizing_coefficients": override}})
    assert (toml, errors) == (public, [])
    resolved, errors = resolve_parameters(cli_overrides=cli)
    assert errors == []
    placement_weights = {
        "timing_wns_coeff": 2.5,
        "timing_tns_coeff": 0.025,
        "timing_slew_weight": 3.0,
        "timing_cap_weight": 4.0,
        "timing_grad_balance_weight": 7.0,
        "timing_grad_balance_target_ratio": 0.2,
    }
    workspace = Workspace(
        directory=tmp_path / "workspace",
        design=OriginDesign(name="gcd"),
        pdk=PDK(tech="tech.lef", lefs=["std.lef"]),
        parameters=make_ics55_parameters(
            {
                "dreamplace": placement_weights,
                "config_overrides": build_config_overrides(resolved),
            }
        ),
    )
    step = builder.build_step(
        workspace,
        StepEnum.DIFF_SIZING.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    init_workspace_config(workspace)
    original_config = workspace.config["dreamplace"].read_bytes()
    monkeypatch.setattr(builder.ecc_builder, "build_step_config", lambda *_: None)
    builder.build_step_config(workspace, step)
    saved = json_read(builder.step_config_path(workspace, step))
    expected_policy = dreamplace_default_config["diff_sizing_coefficients"] | override
    expected = {
        "diff_sizing_coefficients": expected_policy,
        "timing_wns_coeff": expected_policy["wns"],
        "timing_tns_coeff": expected_policy["tns"],
        "timing_cap_weight": expected_policy["cap"],
        "timing_slew_weight": expected_policy["slew"],
        "timing_grad_balance_weight": 1.0,
        "timing_grad_balance_target_ratio": 0.0,
        "timing_opt_coefficients": dreamplace_default_config["timing_opt_coefficients"],
    }
    assert {key: saved[key] for key in expected} == expected
    assert workspace.config["dreamplace"].read_bytes() == original_config
    module = DreamplaceModule(workspace, step, None, None, None, None, None)
    sizing = module._build_params(Params, mode=DreamplaceRunMode.DIFF_SIZING)
    assert {key: getattr(sizing, key) for key in expected} == expected
    placement_step = builder.build_step(
        workspace,
        StepEnum.PLACEMENT.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    builder.build_step_config(workspace, placement_step)
    placement_module = DreamplaceModule(workspace, placement_step, None, None, None, None, None)
    placement = placement_module._build_params(Params, mode=DreamplaceRunMode.PLACEMENT)
    assert {key: getattr(placement, key) for key in placement_weights} == placement_weights


def test_old_config_uses_s50_defaults_without_inheriting_gp_weights(dreamplace_default_config):
    config = dreamplace_default_config.copy()
    policy = config.pop("diff_sizing_coefficients")
    config.update(timing_wns_coeff=3.0, timing_tns_coeff=0.03, timing_grad_balance_weight=7.0)
    actual = builder._apply_diff_sizing_defaults(config)
    assert {
        key: actual[key]
        for key in ("timing_wns_coeff", "timing_tns_coeff", "timing_grad_balance_weight")
    } == {
        "timing_wns_coeff": policy["wns"],
        "timing_tns_coeff": policy["tns"],
        "timing_grad_balance_weight": 1.0,
    }


@pytest.mark.parametrize("steps", [0, 1, 3])
def test_public_continuous_steps_parse_and_resolve(steps):
    expected = {"place.diff_sizing_continuous_steps": steps}
    cli, errors = parse_cli_overrides([f"place.diff_sizing_continuous_steps={steps}"])
    assert (cli, errors) == (expected, [])
    toml, errors = parse_toml_params({"place": {"diff_sizing_continuous_steps": steps}})
    assert (toml, errors) == (expected, [])
    resolved, errors = resolve_parameters(cli_overrides=cli)
    assert errors == []
    actual = next(
        item.value for item in resolved if item.param == "place.diff_sizing_continuous_steps"
    )
    assert actual == steps


@pytest.mark.parametrize(
    ("steps", "parameterization", "execution", "dynamics"),
    [
        (1, "real_size", "warmup_to_discrete", "none"),
        (3, "real_size", "warmup_to_discrete", "none"),
        (0, "logits", "continuous_only", "discrete_gradient_topk"),
    ],
)
def test_diff_sizing_continuous_steps_selects_the_sizing_entry_path(
    dreamplace_default_config, steps, parameterization, execution, dynamics
):
    config = dreamplace_default_config | {"diff_sizing_continuous_steps": steps}
    actual = builder._apply_diff_sizing_defaults(config)
    assert {
        key: actual[key]
        for key in (
            "diff_sizing_continuous_steps",
            "sizing_parameterization",
            "real_size_execution_mode",
            "real_size_warmup_steps",
            "continuous_size_dynamics_mode",
        )
    } == {
        "diff_sizing_continuous_steps": steps,
        "sizing_parameterization": parameterization,
        "real_size_execution_mode": execution,
        "real_size_warmup_steps": steps,
        "continuous_size_dynamics_mode": dynamics,
    }


@pytest.mark.parametrize(
    "policy",
    [[500, 5, 1, 1], {"wns": -1}, {"tns": float("nan")}, {"cap": True}, {"alpha": 7}],
)
def test_invalid_s50_policy_fails_before_config_mutation(policy):
    config = {"diff_sizing_coefficients": policy}
    with pytest.raises(ValueError, match="diff_sizing_coefficients"):
        builder._apply_diff_sizing_defaults(config)
    assert list(config) == ["diff_sizing_coefficients"]
