"""Configuration and step-boundary tests for the placement-parasitic diff_opt flow."""

import json
from typing import Any

import pytest

from chipcompiler.cli.project.params import parse_cli_overrides, resolve_parameters
from chipcompiler.data import EccData, EccStep, OriginDesign, StepEnum, Workspace
from chipcompiler.rtl2gds.builder import build_flow_range
from chipcompiler.tools.ecc_dreamplace.diff_opt import apply_diff_opt_defaults
from chipcompiler.tools.ecc_dreamplace.module import DreamplaceModule, DreamplaceRunMode
from chipcompiler.utility import json_write


def test_diff_opt_parser_preserves_configured_flows_and_uses_placement_parasitics(
    dreamplace_default_config,
):
    from dreamplace.flows.diff_opt_spec import canonical_diff_opt_flows

    mode, flows = canonical_diff_opt_flows(
        dreamplace_default_config["diff_optimization_mode"],
        dreamplace_default_config["diff_optimization_flows"],
    )
    config = apply_diff_opt_defaults(dreamplace_default_config)

    assert config["diff_opt_enabled"] == 1
    assert config["diff_opt_mode"] == mode
    assert config["diff_opt_parasitic_source"] == "placement"
    assert config["flow_kind"] == "placement"
    assert config["timing_rc_mode"] == "placement"
    assert config["timing_objective_lane"] == "timing_slew_cap"
    assert config["timing_action_gradient_mode"] == "off"
    assert config["diff_optimization_flows"] == flows


def test_diff_opt_joint_expands_to_zero_gp_and_rejects_route_parasitics(
    dreamplace_default_config,
):
    config = dreamplace_default_config | {
        "diff_optimization_mode": "joint",
        "diff_optimization_flows": [
            ["sz", 2, [100.0, 1.0, 1.0, 1.0]],
            ["bf", 1, [500.0, 5.0, 1.0, 1.0]],
        ],
    }
    resolved = apply_diff_opt_defaults(config)

    assert resolved["flow_kind"] == "placement"
    assert resolved["diff_opt_mode"] == "joint"
    assert resolved["timing_objective_lane"] == "timing_slew_cap"
    stage = resolved["global_place_stages"][0]
    assert {key: stage[key] for key in ("num_bins_x", "num_bins_y", "iteration", "optimizer")} == {
        "num_bins_x": 512,
        "num_bins_y": 512,
        "iteration": 0,
        "optimizer": "adam",
    }
    with pytest.raises(ValueError, match="only placement parasitic"):
        apply_diff_opt_defaults(config | {"diff_opt_parasitic_source": "rrr"})

    defaults = apply_diff_opt_defaults(
        dreamplace_default_config
        | {"diff_optimization_mode": "joint", "diff_optimization_flows": None}
    )
    assert defaults["diff_optimization_flows"] == [
        ["sz", 5, {"wns": 500.0, "tns": 5.0, "slew": 1.0, "cap": 1.0}],
        ["bf", 1, {"wns": 500.0, "tns": 5.0, "slew": 1.0, "cap": 1.0}],
    ]


def test_diff_opt_rejects_conflicting_explicit_legacy_buffering_fields(
    dreamplace_default_config,
):
    with pytest.raises(ValueError, match="diff_buffering_rounds"):
        apply_diff_opt_defaults(
            dreamplace_default_config
            | {
                "diff_optimization_mode": "buffering",
                "diff_optimization_flows": [
                    ["bf", 10, [500.0, 5.0, 1.0, 1.0]],
                ],
                "diff_buffering_rounds": 5,
            }
        )

    with pytest.raises(ValueError, match="legacy"):
        apply_diff_opt_defaults(
            dreamplace_default_config
            | {
                "diff_optimization_mode": "joint",
                "diff_optimization_flows": [
                    ["sz", 5, [500.0, 5.0, 1.0, 1.0]],
                    ["bf", 1, [500.0, 5.0, 1.0, 1.0]],
                ],
                "diff_buffering_coefficients": {"wns": 100.0},
            }
        )


def test_diff_opt_public_fields_are_scoped_to_diff_opt():
    payload = {
        "place.diff_optimization_mode": "joint",
        "place.diff_optimization_flows": [
            ["sz", 2, [100.0, 1.0, 1.0, 1.0]],
            ["bf", 1, [500.0, 5.0, 1.0, 1.0]],
        ],
    }
    cli, errors = parse_cli_overrides(
        [
            "place.diff_optimization_mode=joint",
            "place.diff_optimization_flows=" + json.dumps(payload["place.diff_optimization_flows"]),
        ]
    )
    assert errors == []
    resolved, errors = resolve_parameters(cli_overrides=cli)
    assert errors == []
    values = {item.param: item.value for item in resolved}
    assert values["place.diff_optimization_mode"] == "joint"
    assert values["place.diff_optimization_flows"] == payload["place.diff_optimization_flows"]


def test_diff_opt_replaces_diff_buffering_but_keeps_diff_sizing():
    chain = build_flow_range("place", "diff_sizing")
    assert [(step.value, tool) for step, tool, _state in chain] == [
        (StepEnum.PLACEMENT.value, "dreamplace"),
        (StepEnum.DIFF_OPT.value, "dreamplace"),
        (StepEnum.DIFF_SIZING.value, "dreamplace"),
    ]


@pytest.mark.parametrize(
    ("overrides", "flow_kind"),
    [
        ({}, "placement"),
        ({"diff_optimization_mode": "buffering", "diff_optimization_flows": None}, "buffering"),
    ],
)
def test_diff_opt_module_uses_placement_rc_and_own_result_directory(
    tmp_path, dreamplace_default_config, overrides, flow_kind
):
    config_path = tmp_path / "dreamplace_ecc.json"
    table_path = tmp_path / "buffer_drive_strength.json"
    table_path.write_text("{}")
    json_write(
        config_path,
        dreamplace_default_config
        | overrides
        | {"buffering_candidate_drive_strength_table": str(table_path)},
    )
    result_dir = tmp_path / "data" / "diff_opt"
    step = EccStep(
        name=StepEnum.DIFF_OPT.value,
        data=EccData(dir=tmp_path / "data", steps={StepEnum.DIFF_OPT.value: result_dir}),
    )
    workspace = Workspace(
        directory=tmp_path / "workspace",
        design=OriginDesign(name="gcd"),
        config={"dreamplace": config_path},
    )
    ecc_module: Any = object()
    module = DreamplaceModule(
        workspace,
        step,
        ecc_module,
        tmp_path / "input.def",
        tmp_path / "input.v",
        tmp_path / "output.def",
        tmp_path / "output.v",
    )

    class FakeParams:
        def fromJson(self, data):
            self.__dict__.update(data)

    params = module._build_params(FakeParams, mode=DreamplaceRunMode.DIFF_OPT)
    assert params.flow_kind == flow_kind
    assert params.timing_rc_mode == "placement"
    assert params.diff_opt_parasitic_source == "placement"
    assert params.result_dir == str(result_dir)


@pytest.mark.parametrize(
    "coefficients",
    [
        [100.0, 1.0, 2.0, 3.0],
        {"wns": 100.0, "tns": 1.0, "slew": 2.0, "cap": 3.0},
    ],
)
def test_diff_opt_accepts_equivalent_legacy_and_canonical_buffering_config(
    coefficients,
    dreamplace_default_config,
):
    policy = {"wns": 100.0, "tns": 1.0, "slew": 2.0, "cap": 3.0}
    config = dreamplace_default_config | {
        "diff_optimization_mode": "buffering",
        "diff_buffering_rounds": 3,
        "diff_buffering_coefficients": policy,
        "diff_optimization_flows": [["bf", 3, coefficients]],
    }
    result = apply_diff_opt_defaults(config)
    assert result["diff_optimization_flows"] == [["bf", 3, policy]]
    assert {
        "wns": result["timing_wns_coeff"],
        "tns": result["timing_tns_coeff"],
        "slew": result["timing_slew_weight"],
        "cap": result["timing_cap_weight"],
    } == policy
