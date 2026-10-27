"""Config isolation and the native refresh/legalization boundary of diff buffering."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from chipcompiler.cli.project.params import (
    build_config_overrides,
    parse_cli_overrides,
    resolve_parameters,
)
from chipcompiler.data import PDK, OriginDesign, StepEnum, Workspace
from chipcompiler.data.workspace import init_workspace_config
from chipcompiler.rtl2gds.builder import build_flow_range
from chipcompiler.tools.ecc_dreamplace import builder
from chipcompiler.tools.ecc_dreamplace.diff_buffering import finalize_diff_buffering
from chipcompiler.tools.ecc_dreamplace.module import DreamplaceModule, DreamplaceRunMode
from chipcompiler.utility import json_read


@pytest.mark.parametrize(
    "overrides", [{}, {"rounds": 3, "selection_fraction": 0.01, "coefficients": {"tns": 10.0}}]
)
def test_buffering_step_resolves_independently_of_placement(
    tmp_path, monkeypatch, make_ics55_parameters, dreamplace_default_config, overrides
):
    from dreamplace.flows.buffer_drive_table import EXPECTED_DRIVE_TYPE_MASTERS
    from dreamplace.Params import Params

    cli, errors = parse_cli_overrides(
        [
            "place.diff_optimization_mode=buffering",
            "place.diff_optimization_flows=null",
            *[
                f"place.diff_buffering_{key}={json.dumps(value)}"
                for key, value in overrides.items()
            ],
        ]
    )
    assert errors == []
    resolved, errors = resolve_parameters(cli_overrides=cli)
    assert errors == []
    workspace = Workspace(
        directory=tmp_path / "workspace",
        design=OriginDesign(name="gcd"),
        pdk=PDK(
            name="ics55",
            tech=Path("tech.lef"),
            lefs=[Path("std.lef")],
            buffers=list(EXPECTED_DRIVE_TYPE_MASTERS),
        ),
        parameters=make_ics55_parameters({"config_overrides": build_config_overrides(resolved)}),
    )
    step = builder.build_step(
        workspace, StepEnum.DIFF_BUFFERING.value, tmp_path / "placed.def", tmp_path / "placed.v"
    )
    init_workspace_config(workspace)
    original = workspace.config["dreamplace"].read_bytes()
    monkeypatch.setattr(builder.ecc_builder, "build_step_config", lambda *_: None)
    builder.build_step_config(workspace, step)
    assert workspace.config["dreamplace"].read_bytes() == original
    config = json_read(builder.step_config_path(workspace, step))
    policy = dreamplace_default_config["diff_buffering_coefficients"] | overrides.get(
        "coefficients", {}
    )
    expected = {
        "flow_kind": "buffering",
        "placement_sizing_mode": "place_only",
        "random_center_init_flag": 0,
        "cell_padding_x": 0,
        "continuous_size_dynamics_mode": "none",
        "buffering_candidate_drive_type_mode": "four_strength_table",
        "buffering_candidate_strategy": "discrete_net_gradient",
        "buffering_continuous_steps": overrides.get(
            "rounds", dreamplace_default_config["diff_buffering_rounds"]
        ),
        "buffering_route_b_selection_fraction": overrides.get(
            "selection_fraction", dreamplace_default_config["diff_buffering_selection_fraction"]
        ),
        "timing_wns_coeff": policy["wns"],
        "timing_tns_coeff": policy["tns"],
        "timing_slew_weight": policy["slew"],
        "timing_cap_weight": policy["cap"],
        "timing_grad_balance_weight": 1.0,
        "timing_grad_balance_target_ratio": 0.0,
        "joint_post_commit_continue": False,
    }
    assert {key: config[key] for key in expected} == expected
    assert (
        config["diff_sizing_coefficients"] == dreamplace_default_config["diff_sizing_coefficients"]
    )
    params = DreamplaceModule(workspace, step, None, None, None, None, None)._build_params(
        Params, mode=DreamplaceRunMode.DIFF_BUFFERING
    )
    assert {key: getattr(params, key) for key in expected} == expected
    table = json_read(config["buffering_candidate_drive_strength_table"])
    assert tuple(row["master_name"] for row in table["buffers"]) == EXPECTED_DRIVE_TYPE_MASTERS


def test_placement_candidate_mode_expands_internal_lane_settings(monkeypatch):
    workspace: Any = SimpleNamespace()
    step: Any = SimpleNamespace(name=StepEnum.PLACEMENT.value)
    monkeypatch.setattr(
        builder,
        "prepare_diff_opt_drive_table",
        lambda _workspace, _step, params: params
        | {"buffering_candidate_drive_strength_table": "generated.json"},
    )

    config, internal_keys = builder._apply_placement_buffering_profile(
        workspace, step, {"buffering_mode": "candidate"}
    )

    assert config == {
        "buffering_mode": "candidate",
        "buffering_segment_strategy": "continuous",
        "buffering_candidate_strategy": "discrete_net_gradient",
        "buffering_candidate_drive_type_mode": "four_strength_table",
        "buffering_candidate_drive_strength_table": "generated.json",
        "buffering_continuous_steps": 1,
        "buffering_fixed_buffer_master": "",
        "buffering_fixed_bsu_index": None,
    }
    assert internal_keys == {
        "buffering_segment_strategy",
        "buffering_candidate_strategy",
        "buffering_candidate_drive_type_mode",
        "buffering_candidate_drive_strength_table",
        "buffering_continuous_steps",
        "buffering_fixed_buffer_master",
        "buffering_fixed_bsu_index",
    }


def test_placement_range_connects_diff_opt_to_sizing():
    chain = build_flow_range("place", "diff_sizing")
    assert [(step.value, tool) for step, tool, _state in chain] == [
        (StepEnum.PLACEMENT.value, "dreamplace"),
        (StepEnum.DIFF_OPT.value, "dreamplace"),
        (StepEnum.DIFF_SIZING.value, "dreamplace"),
    ]


def test_terminal_refresh_discards_virtual_model_before_legalization(monkeypatch, tmp_path):
    import dreamplace.NonLinearPlace as nonlinear

    calls = []
    commit = {"status": "accepted", "accepted_action_count": 4}
    old = SimpleNamespace(
        last_buffering_lane_summary={
            "status": "completed",
            "commit": commit,
            "inner_loop": {"iterations": 2},
        }
    )
    timing = {"wns": -10.0, "tns": -20.0}

    class TerminalPlacer:
        def __init__(self, params, placedb, _timer):
            calls.append("new_placer")
            actual = {
                key: getattr(params, key)
                for key in [
                    "flow_kind",
                    "global_place_flag",
                    "legalize_flag",
                    "enable_relaxed_buffer_timing",
                    "buffering_continuous_relaxed_optimization",
                ]
            }
            assert actual == {
                "flow_kind": "placement",
                "global_place_flag": 0,
                "legalize_flag": 1,
                "enable_relaxed_buffer_timing": False,
                "buffering_continuous_relaxed_optimization": 0,
            }
            assert placedb.cooptimization_geometry is None
            self.pos = [object()]
            self.op_collections = SimpleNamespace(legality_check_op=lambda _pos: True)

        def __call__(self, _params, _placedb):
            calls.append("legalize")
            return 1.0, 2.0, {}

        def run_sta_only(self, _params, _placedb):
            calls.append("sta")
            assert _params.timing_aggregation_mode == "hard"
            return float("inf"), float("inf"), {"timing_stage_summary": {"sta": timing}}

    def refresh(**kwargs):
        assert kwargs == {"refresh_mode": "full_rebuild", "rebuild_mode": "full_rebuild"}
        calls.append("refresh")
        return {"status": "ok"}

    engine = SimpleNamespace(
        params=SimpleNamespace(result_dir=str(tmp_path)),
        placedb=SimpleNamespace(cooptimization_geometry=object()),
        placer=old,
        _physical_mutation_backend=lambda: SimpleNamespace(refresh=refresh),
    )
    monkeypatch.setattr(nonlinear, "NonLinearPlace", TerminalPlacer)
    result = finalize_diff_buffering(engine)
    assert calls == ["refresh", "new_placer", "legalize", "sta"]
    assert engine.placer is not old
    assert {
        key: result[key]
        for key in [
            "status",
            "legal",
            "new_gp_optimizer_steps",
            "sizing_steps",
            "virtual_count",
            "final_timing",
        ]
    } == {
        "status": "ok",
        "legal": True,
        "new_gp_optimizer_steps": 0,
        "sizing_steps": 0,
        "virtual_count": 0,
        "final_timing": timing,
    }
    assert json.loads((tmp_path / "diff_buffering_summary.json").read_text()) == result
