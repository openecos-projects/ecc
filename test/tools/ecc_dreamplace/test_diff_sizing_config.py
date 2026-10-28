"""Independent S50 coefficients through public overrides and step resolution."""

import json
from pathlib import Path

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
    from dreamplace.flows.diff_sizing import _validate_action_profile
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
        pdk=PDK(tech=Path("tech.lef"), lefs=[Path("std.lef")]),
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
        "diff_sizing_optimization_flows": [["up", 50, expected_policy, 1.0]],
        "gpugr_bottom_routing_layer": "MET2",
        "gpugr_top_routing_layer": "MET5",
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
    (phase,) = _validate_action_profile(sizing)
    assert (phase.to_list(), phase.action_mask) == (
        expected["diff_sizing_optimization_flows"][0],
        (True, False, False, True),
    )
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
    config.update(
        timing_wns_coeff=3.0,
        timing_tns_coeff=0.03,
        timing_grad_balance_weight=7.0,
        gpugr_bottom_routing_layer="",
        gpugr_top_routing_layer="",
    )
    actual = builder._apply_diff_sizing_defaults(config)
    assert {
        key: actual[key]
        for key in (
            "gpugr_bottom_routing_layer",
            "gpugr_top_routing_layer",
            "timing_wns_coeff",
            "timing_tns_coeff",
            "timing_grad_balance_weight",
        )
    } == {
        "gpugr_bottom_routing_layer": "MET2",
        "gpugr_top_routing_layer": "MET5",
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


@pytest.mark.parametrize("enabled", [0, 1])
def test_public_terminal_gr_sta_flag_parse_and_resolve(enabled):
    expected = {"place.diff_sizing_terminal_gr_sta_enabled": enabled}
    cli, errors = parse_cli_overrides([f"place.diff_sizing_terminal_gr_sta_enabled={enabled}"])
    assert (cli, errors) == (expected, [])
    toml, errors = parse_toml_params({"place": {"diff_sizing_terminal_gr_sta_enabled": enabled}})
    assert (toml, errors) == (expected, [])
    resolved, errors = resolve_parameters(cli_overrides=cli)
    assert errors == []
    actual = next(
        item.value for item in resolved if item.param == "place.diff_sizing_terminal_gr_sta_enabled"
    )
    assert actual == enabled


def test_public_action_gradient_mode_parses_and_resolves():
    expected = {"place.timing_action_gradient_mode": "lut_action"}
    cli, errors = parse_cli_overrides(["place.timing_action_gradient_mode=lut_action"])
    assert (cli, errors) == (expected, [])
    toml, errors = parse_toml_params({"place": {"timing_action_gradient_mode": "lut_action"}})
    assert (toml, errors) == (expected, [])
    resolved, errors = resolve_parameters(cli_overrides=cli)
    assert errors == []
    actual = next(
        item.value for item in resolved if item.param == "place.timing_action_gradient_mode"
    )
    assert actual == "lut_action"


@pytest.mark.parametrize("objective", ["loss", "tns", "wns"])
def test_public_action_score_objective_parses_and_resolves(objective):
    expected = {"place.timing_action_score_objective": objective}
    cli, errors = parse_cli_overrides([f"place.timing_action_score_objective={objective}"])
    assert (cli, errors) == (expected, [])
    toml, errors = parse_toml_params({"place": {"timing_action_score_objective": objective}})
    assert (toml, errors) == (expected, [])
    resolved, errors = resolve_parameters(cli_overrides=cli)
    assert errors == []
    actual = next(
        item.value for item in resolved if item.param == "place.timing_action_score_objective"
    )
    assert actual == objective


@pytest.mark.parametrize("rc_mode", ["placement", "gr"])
def test_public_diff_sizing_timing_rc_mode_parses_and_resolves(rc_mode):
    expected = {"place.diff_sizing_timing_rc_mode": rc_mode}
    cli, errors = parse_cli_overrides([f"place.diff_sizing_timing_rc_mode={rc_mode}"])
    assert (cli, errors) == (expected, [])
    toml, errors = parse_toml_params({"place": {"diff_sizing_timing_rc_mode": rc_mode}})
    assert (toml, errors) == (expected, [])
    resolved, errors = resolve_parameters(cli_overrides=cli)
    assert errors == []
    actual = next(
        item.value for item in resolved if item.param == "place.diff_sizing_timing_rc_mode"
    )
    assert actual == rc_mode


def test_diff_sizing_timing_rc_mode_defaults_to_gr_and_respects_explicit_choice(
    dreamplace_default_config,
):
    default = builder._apply_diff_sizing_defaults(dreamplace_default_config)
    assert default["timing_rc_mode"] == "gr"
    assert default["diff_sizing_timing_rc_mode"] == "gr"

    explicit = builder._apply_diff_sizing_defaults(
        dreamplace_default_config | {"diff_sizing_timing_rc_mode": "placement"},
        explicit_keys={"diff_sizing_timing_rc_mode"},
    )
    assert explicit["timing_rc_mode"] == "placement"
    assert explicit["gr_sizing_rrr_iters"] == 0

    legacy_name = builder._apply_diff_sizing_defaults(
        dreamplace_default_config | {"timing_rc_mode": "placement"},
        explicit_keys={"timing_rc_mode"},
    )
    assert legacy_name["timing_rc_mode"] == "placement"
    assert legacy_name["diff_sizing_timing_rc_mode"] == "placement"


def test_public_diff_sizing_optimization_flows_parse_and_resolve():
    flows = [
        ["up", 10, [500, 5, 1, 1], 1],
        ["down", 1, [500, 5, 1, 1], 0.1],
        ["quad", 10, [500, 5, 1, 1], 1],
    ]
    expected = {"place.diff_sizing_optimization_flows": flows}
    cli, errors = parse_cli_overrides(["place.diff_sizing_optimization_flows=" + json.dumps(flows)])
    assert (cli, errors) == (expected, [])
    toml, errors = parse_toml_params({"place": {"diff_sizing_optimization_flows": flows}})
    assert (toml, errors) == (expected, [])
    resolved, errors = resolve_parameters(cli_overrides=cli)
    assert errors == []
    actual = next(
        item.value for item in resolved if item.param == "place.diff_sizing_optimization_flows"
    )
    assert actual == flows


def test_diff_sizing_optimization_flows_set_total_stage_rounds(
    dreamplace_default_config,
):
    actual = builder._apply_diff_sizing_defaults(
        dreamplace_default_config
        | {
            "diff_sizing_optimization_flows": [
                ["up", 2, [500, 5, 1, 1], 1],
                ["down", 1, [100, 2, 3, 4], 0.1],
                ["quad", 3, [10, 1, 1, 1], 5],
            ]
        }
    )
    assert actual["diff_sizing_optimization_flows"] == [
        ["up", 2, {"wns": 500.0, "tns": 5.0, "slew": 1.0, "cap": 1.0}, 1.0],
        ["down", 1, {"wns": 100.0, "tns": 2.0, "slew": 3.0, "cap": 4.0}, 0.1],
        ["quad", 3, {"wns": 10.0, "tns": 1.0, "slew": 1.0, "cap": 1.0}, 5.0],
    ]
    assert actual["global_place_stages"][0]["iteration"] == 6


def test_diff_sizing_optimization_flows_require_action_mode(
    dreamplace_default_config,
):
    with pytest.raises(ValueError, match="timing_action_gradient_mode=lut_action"):
        builder._apply_diff_sizing_defaults(
            dreamplace_default_config
            | {
                "timing_action_gradient_mode": "off",
                "diff_sizing_optimization_flows": [["up", 1, [500, 5, 1, 1], 1]],
            }
        )


@pytest.mark.parametrize(
    "flows",
    [
        [["sideways", 1, [500, 5, 1, 1], 1]],
        [["up", 0, [500, 5, 1, 1], 1]],
        [["up", 1, [500, 5, 1, 1], 0]],
    ],
)
def test_diff_sizing_optimization_flows_reject_invalid_phases(dreamplace_default_config, flows):
    with pytest.raises(ValueError):
        builder._apply_diff_sizing_defaults(
            dreamplace_default_config | {"diff_sizing_optimization_flows": flows}
        )


@pytest.mark.parametrize(
    ("extra_args", "expected_rc_mode"),
    [
        ([], "gr"),
        (["place.timing_rc_mode=placement"], "placement"),
        (["place.diff_sizing_timing_rc_mode=placement"], "placement"),
    ],
)
def test_public_lut_action_mode_survives_step_resolution(
    tmp_path, monkeypatch, make_ics55_parameters, extra_args, expected_rc_mode
):
    from dreamplace.Params import Params

    cli, errors = parse_cli_overrides(["place.timing_action_gradient_mode=lut_action", *extra_args])
    assert errors == []
    resolved, errors = resolve_parameters(cli_overrides=cli)
    assert errors == []
    workspace = Workspace(
        directory=tmp_path / "workspace",
        design=OriginDesign(name="gcd"),
        pdk=PDK(tech=Path("tech.lef"), lefs=[Path("std.lef")]),
        parameters=make_ics55_parameters({"config_overrides": build_config_overrides(resolved)}),
    )
    step = builder.build_step(
        workspace,
        StepEnum.DIFF_SIZING.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    init_workspace_config(workspace)
    monkeypatch.setattr(builder.ecc_builder, "build_step_config", lambda *_: None)
    builder.build_step_config(workspace, step)
    saved = json_read(builder.step_config_path(workspace, step))
    assert saved["timing_action_gradient_mode"] == "lut_action"
    assert saved["timing_rc_mode"] == expected_rc_mode
    assert saved["gr_sizing_rrr_iters"] == (3 if expected_rc_mode == "gr" else 0)
    assert {
        key: saved[key]
        for key in (
            "sizing_parameterization",
            "real_size_execution_mode",
            "real_size_warmup_steps",
            "continuous_size_dynamics_mode",
            "timing_action_score_objective",
        )
    } == {
        "sizing_parameterization": "real_size",
        "real_size_execution_mode": "continuous_only",
        "real_size_warmup_steps": 0,
        "continuous_size_dynamics_mode": "none",
        "timing_action_score_objective": "loss",
    }
    module = DreamplaceModule(workspace, step, None, None, None, None, None)
    sizing = module._build_params(Params, mode=DreamplaceRunMode.DIFF_SIZING)
    assert sizing.timing_action_gradient_mode == "lut_action"
    assert sizing.timing_action_score_objective == "loss"
    assert sizing.timing_rc_mode == expected_rc_mode
    assert sizing.gr_sizing_rrr_iters == (3 if expected_rc_mode == "gr" else 0)
    assert sizing.sizing_parameterization == "real_size"
    assert sizing.continuous_size_dynamics_mode == "none"


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
    config = dreamplace_default_config | {
        "diff_sizing_continuous_steps": steps,
        "timing_action_gradient_mode": "off",
    }
    actual = builder._apply_diff_sizing_defaults(config)
    assert {
        key: actual[key]
        for key in (
            "diff_sizing_continuous_steps",
            "sizing_parameterization",
            "real_size_execution_mode",
            "real_size_warmup_steps",
            "continuous_size_dynamics_mode",
            "diff_sizing_optimization_flows",
        )
    } == {
        "diff_sizing_continuous_steps": steps,
        "sizing_parameterization": parameterization,
        "real_size_execution_mode": execution,
        "real_size_warmup_steps": steps,
        "continuous_size_dynamics_mode": dynamics,
        "diff_sizing_optimization_flows": None,
    }


def test_diff_sizing_lut_action_keeps_real_size_materialization(
    dreamplace_default_config,
):
    config = dreamplace_default_config | {
        "timing_action_gradient_mode": "lut_action",
    }
    actual = builder._apply_diff_sizing_defaults(config)
    assert {
        key: actual[key]
        for key in (
            "sizing_parameterization",
            "real_size_execution_mode",
            "real_size_warmup_steps",
            "continuous_size_dynamics_mode",
            "timing_action_score_objective",
        )
    } == {
        "sizing_parameterization": "real_size",
        "real_size_execution_mode": "continuous_only",
        "real_size_warmup_steps": 0,
        "continuous_size_dynamics_mode": "none",
        "timing_action_score_objective": "loss",
    }
    with pytest.raises(ValueError, match="diff_sizing_continuous_steps=0"):
        builder._apply_diff_sizing_defaults(config | {"diff_sizing_continuous_steps": 3})
    with pytest.raises(ValueError, match="timing_action_score_objective"):
        builder._apply_diff_sizing_defaults(config | {"timing_action_score_objective": "slack"})


@pytest.mark.parametrize(
    "policy",
    [[500, 5, 1, 1], {"wns": -1}, {"tns": float("nan")}, {"cap": True}, {"alpha": 7}],
)
def test_invalid_s50_policy_fails_before_config_mutation(policy):
    config = {"diff_sizing_coefficients": policy}
    with pytest.raises(ValueError, match="diff_sizing_coefficients"):
        builder._apply_diff_sizing_defaults(config)
    assert list(config) == ["diff_sizing_coefficients"]
