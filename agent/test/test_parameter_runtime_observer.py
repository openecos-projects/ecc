import json
from contextlib import ExitStack
from threading import Thread
from types import SimpleNamespace

from agent.data.floorplan_parameter_observer import build_floorplan_report
from agent.data.parameter_runtime_observer import (
    DreamplaceRecorder,
    _build_dreamplace_report,
    _invoke_and_record,
    _native_value,
    _observe_native_model,
    _patch_method,
)


class _Scalar:
    def __init__(self, value):
        self.value = value

    def item(self):
        return self.value


def _engine(*, params, target_density=0.8, padding_sites=2):
    return SimpleNamespace(
        params=params,
        placer=SimpleNamespace(
            data_collections=SimpleNamespace(target_density=_Scalar(target_density))
        ),
        placedb=SimpleNamespace(
            cell_padding_x=padding_sites,
            num_movable_nodes=12,
        ),
        metrics={"overflow": [0.7, _Scalar(0.12), 0.08]},
    )


def test_density_weight_report_tracks_internal_values_not_only_configured_value(tmp_path):
    params = SimpleNamespace(density_weight=0.001)
    probe = {
        "density_weight_initializations": [0.004],
        "density_weight_updates": [{"sequence": 0, "before": 0.004, "after": 0.006}],
        "final_internal_density_weight": 0.009,
    }

    report = _build_dreamplace_report(
        {"knob_id": "place.density_weight", "value": 0.001},
        _engine(params=params),
        {"iteration": 5, "objective": 12.5},
        probe,
        engine_succeeded=True,
    )

    observation = report["consumer_observation"]
    assert observation["configured_density_weight"] == 0.001
    assert observation["internal_initial_density_weight"] == 0.004
    assert observation["final_internal_density_weight"] == 0.009
    assert report["effective_initial"] == {
        "value": 0.004,
        "unit": "internal_objective_weight",
    }
    assert report["effective_final"] == {
        "value": 0.009,
        "unit": "internal_objective_weight",
    }
    assert observation["lifecycle"] == [
        {
            "sequence": 0,
            "phase": "adopted",
            "value": 0.004,
            "unit": "internal_objective_weight",
            "evidence_kind": "direct_python_runtime",
        },
        {
            "sequence": 1,
            "phase": "evolved",
            "value": 0.009,
            "unit": "internal_objective_weight",
            "evidence_kind": "direct_python_runtime",
        },
    ]


def test_target_density_report_requires_operator_call_and_records_floor_override(tmp_path):
    params = SimpleNamespace(target_density=0.65)
    report = _build_dreamplace_report(
        {"knob_id": "place.target_density", "value": 0.2},
        _engine(params=params, target_density=0.6499999761581421),
        {"iteration": 4},
        {"density_operator_call_count": 3},
        engine_succeeded=True,
    )

    assert report["activation"]["status"] == "used"
    assert report["effective_initial"] == {"value": 0.65, "unit": "ratio"}
    assert report["transitions"] == [
        {
            "sequence": 0,
            "from": "materialized",
            "to": "overridden",
            "value": 0.65,
            "reason": "DREAMPlace utilization lower bound",
            "rule_id": "dreamplace.target_density.utilization_floor",
            "evidence_ref": "analysis/parameter_runtime_report.v1.json",
            "evidence_sha256": report["activation"]["consumers"][0]["evidence_sha256"],
        }
    ]


def test_target_overflow_report_binds_threshold_to_running_predicate_owner(tmp_path):
    params = SimpleNamespace(stop_overflow=0.1)
    report = _build_dreamplace_report(
        {"knob_id": "place.target_overflow", "value": 0.1},
        _engine(params=params),
        {"iteration": 7, "overflow": 0.08},
        {
            "nonlinear_place_call_count": 1,
            "stop_overflow_read_count": 4,
        },
        engine_succeeded=True,
    )

    observation = report["consumer_observation"]
    assert report["activation"]["status"] == "used"
    assert report["activation"]["consumers"][0]["outcome"] == "evaluated"
    assert observation["predicate_owner_call_count"] == 1
    assert observation["threshold_read_count"] == 4
    assert observation["observed_overflow_count"] == 3
    assert observation["threshold_reached"] is True
    assert observation["lifecycle"][1]["evidence_kind"] == "direct_python_runtime"


def test_routability_report_distinguishes_disabled_gate_from_entered_branch(tmp_path):
    disabled = _build_dreamplace_report(
        {"knob_id": "place.routability_opt", "value": False},
        _engine(params=SimpleNamespace(routability_opt_flag=False)),
        {"iteration": 3},
        {
            "place_object_count": 1,
            "routability_operator_constructed": False,
            "routability_branch_round_count": 0,
        },
        engine_succeeded=True,
    )
    entered = _build_dreamplace_report(
        {"knob_id": "place.routability_opt", "value": True},
        _engine(params=SimpleNamespace(routability_opt_flag=True)),
        {"iteration": 3},
        {
            "place_object_count": 1,
            "routability_operator_constructed": True,
            "routability_branch_round_count": 1,
        },
        engine_succeeded=True,
    )

    assert disabled["activation"]["status"] == "not_activated"
    assert disabled["activation"]["consumers"][0]["outcome"] == "evaluated"
    assert entered["activation"]["status"] == "used"
    assert entered["consumer_observation"]["branch_round_count"] == 1


def test_padding_report_keeps_written_consumed_internal_and_restored_values_distinct(
    tmp_path,
):
    params = SimpleNamespace(cell_padding_x=0)
    probe = {
        "cell_padding": {
            "normalized_padding_dbu": 400,
            "effective_padding_dbu": 200,
            "geometry_apply_count": 1,
        }
    }

    report = _build_dreamplace_report(
        {"knob_id": "place.cell_padding_x", "value": 400},
        _engine(params=params, padding_sites=1),
        {"iteration": 3},
        probe,
        engine_succeeded=True,
    )

    assert report["effective_initial"] == {"value": 200, "unit": "dbu"}
    assert report["effective_final"] == {"value": 200, "unit": "dbu"}
    assert report["consumer_observation"] == {
        "requested_padding_dbu": 400,
        "normalized_padding_dbu": 400,
        "effective_padding_dbu": 200,
        "effective_padding_sites": 1,
        "post_legalization_padding_sites": 0,
        "representation_restored": True,
        "geometry_apply_count": 1,
        "movable_node_count": 12,
        "placement_iteration_count": 3,
        "evidence_complete": True,
        "lifecycle": [
            {
                "sequence": 0,
                "phase": "normalized",
                "value": 400,
                "unit": "dbu",
                "evidence_kind": "direct_python_runtime",
            },
            {
                "sequence": 1,
                "phase": "consumed",
                "value": 200,
                "unit": "dbu",
                "evidence_kind": "direct_python_runtime",
            },
            {
                "sequence": 2,
                "phase": "restored",
                "value": 0,
                "unit": "internal_site",
                "evidence_kind": "post_run_state",
            },
        ],
    }


def test_floorplan_report_separates_boundary_value_from_realized_geometry(tmp_path):
    config_path = tmp_path / "floorplan.json"
    config_path.write_text(
        json.dumps(
            {
                "die_builder": {
                    "mode": "die_util",
                    "die_util": {"utilization": 0.8, "aspect_ratio": 1.0},
                }
            }
        ),
        encoding="utf-8",
    )
    feature_path = tmp_path / "feature.json"
    feature_path.write_text(
        json.dumps(
            {
                "Design Layout": {
                    "core_area": 800.0,
                    "core_usage": 0.79,
                    "core_bounding_width": 40.0,
                    "core_bounding_height": 20.0,
                }
            }
        ),
        encoding="utf-8",
    )
    boundary = {
        "init_fp_call_count": 1,
        "run_fp_call_count": 1,
        "config_path": str(config_path),
    }

    report = build_floorplan_report(
        {"knob_id": "floorplan.core_util", "value": 0.8},
        boundary,
        feature_path,
        engine_succeeded=True,
    )

    assert report["effective_initial"] == {"value": 0.8, "unit": "ratio"}
    assert report["effective_final"] == {"value": 0.79, "unit": "ratio"}
    observation = report["consumer_observation"]
    assert observation["evidence_kind"] == "boundary_and_derived_output"
    assert observation["realized_core_utilization"] == 0.79
    assert observation["realized_aspect_ratio"] == 2.0
    assert observation["lifecycle"][-1] == {
        "sequence": 2,
        "phase": "realized",
        "value": 0.79,
        "unit": "ratio",
        "evidence_kind": "derived_verified_artifact",
    }


def test_scoped_method_hook_is_restored_after_candidate():
    class Owner:
        def run(self):
            return "original"

    original = Owner.run
    with ExitStack() as stack:
        _patch_method(
            stack,
            Owner,
            "run",
            lambda wrapped, owner: (wrapped(owner), "observed"),
        )
        assert Owner().run() == ("original", "observed")
        assert Owner.run is not original
        foreign_result = []
        thread = Thread(target=lambda: foreign_result.append(Owner().run()))
        thread.start()
        thread.join()
        assert foreign_result == ["original"]

    assert Owner.run is original


def test_native_model_hook_records_density_updates_and_routability_calls():
    recorder = DreamplaceRecorder(
        patch={"knob_id": "place.density_weight", "value": 0.001},
    )
    model = SimpleNamespace(density_weight=0.0)

    def initialize_density_weight():
        model.density_weight = 0.004
        return model.density_weight

    def update_density_weight():
        model.density_weight = 0.006
        return "updated"

    model.initialize_density_weight = initialize_density_weight
    model.op_collections = SimpleNamespace(
        update_density_weight_op=update_density_weight,
        adjust_node_area_op=lambda: "adjusted",
    )

    with ExitStack() as stack:
        _observe_native_model(model, recorder, stack)
        assert model.initialize_density_weight() == 0.004
        assert model.op_collections.update_density_weight_op() == "updated"
    assert recorder.probe["density_weight_initializations"] == [0.004]
    assert recorder.probe["density_weight_updates"] == [
        {"sequence": 0, "before": 0.004, "after": 0.006}
    ]


def test_native_value_preserves_vectors_and_drops_non_finite_values():
    assert _native_value([_Scalar(0.1), _Scalar(0.2)]) == [0.1, 0.2]
    assert _native_value(float("inf")) is None


def test_density_weight_vector_is_preserved_without_claiming_scalar_effectiveness():
    report = _build_dreamplace_report(
        {"knob_id": "place.density_weight", "value": 0.001},
        _engine(params=SimpleNamespace(density_weight=0.001)),
        {"iteration": 4, "objective": 1.0},
        {
            "density_weight_initializations": [[0.004, 0.005]],
            "density_weight_updates": [],
            "final_internal_density_weight": [0.006, 0.007],
        },
        engine_succeeded=True,
    )

    assert report["activation"]["status"] == "unknown"
    assert report["effective_initial"]["value"] is None
    assert report["consumer_observation"]["final_internal_density_weight"] == [
        0.006,
        0.007,
    ]


def test_report_failure_does_not_change_tool_result(monkeypatch, tmp_path):
    failures = []
    workspace = SimpleNamespace(
        directory=tmp_path,
        logger=SimpleNamespace(exception=lambda message: failures.append(message)),
    )

    def fail_write(*_args, **_kwargs):
        raise OSError("read-only analysis directory")

    monkeypatch.setattr(
        "agent.data.parameter_runtime_observer.write_json_atomic",
        fail_write,
    )

    assert _invoke_and_record(workspace, lambda: True, lambda _ok: {}) is True
    assert failures == ["Failed to persist parameter runtime evidence"]
