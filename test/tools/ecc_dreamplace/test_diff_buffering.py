"""Config isolation and the native refresh/legalization boundary of diff buffering."""

import json
from types import SimpleNamespace
from typing import Any

from chipcompiler.data import SkippableStepEnum, StepEnum
from chipcompiler.rtl2gds.builder import build_flow_range
from chipcompiler.tools.ecc_dreamplace import builder
from chipcompiler.tools.ecc_dreamplace.diff_buffering import finalize_diff_buffering


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
        (SkippableStepEnum.DIFF_OPT.value, "dreamplace"),
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
