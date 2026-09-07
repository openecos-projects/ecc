import json
from contextlib import ExitStack
from threading import Thread
from types import SimpleNamespace

import pytest

from agent.data.floorplan_parameter_observer import build_floorplan_report
from agent.data.parameter_runtime_observer import (
    DreamplaceRecorder,
    _build_dreamplace_report,
    _invoke_and_record,
    _observe_cell_padding,
    _observe_native_model,
    _observe_placement_call,
    _patch_method,
)


def _report(knob, value, params, probe, *, succeeded=True):
    return _build_dreamplace_report(
        {"knob_id": knob, "value": value},
        SimpleNamespace(params=SimpleNamespace(**params)),
        {},
        probe,
        engine_succeeded=succeeded,
    )


def test_density_floor_remains_effective_if_later_tool_operation_fails():
    report = _report(
        "place.target_density",
        0.2,
        {},
        {
            "target_density": 0.65,
            "density_tensor_value": 0.64999998,
            "density_operator_call_count": 3,
            "utilization_floor": 0.65,
        },
        succeeded=False,
    )
    assert (report["status"], report["actual_value"]) == ("effective", 0.65)
    assert report["observation"]["utilization_floor"] == 0.65
    assert report["schema_version"] == "tool.parameter_runtime_report.v2"


def test_configured_density_without_consumer_is_unknown():
    report = _report("place.target_density", 0.2, {"target_density": 0.65}, {})
    assert (report["status"], report["actual_value"]) == ("unknown", None)


def test_completed_placement_preserves_overflow_before_later_failure():
    recorder = DreamplaceRecorder({"knob_id": "place.target_overflow", "value": 0.1})
    engine = SimpleNamespace(params=SimpleNamespace(stop_overflow=0.1))

    def place(engine):
        engine.metrics = {"overflow": [0.7, 0.08]}

    _observe_placement_call(recorder, place, engine)
    report = _build_dreamplace_report(
        recorder.patch,
        engine,
        recorder.ppa,
        recorder.probe,
        engine_succeeded=False,
    )
    assert (report["status"], report["actual_value"]) == ("effective", 0.1)


@pytest.mark.parametrize(
    "requested,rounds,completed,status,actual",
    [
        (False, 0, True, "effective", False),
        (True, 1, False, "effective", True),
        (True, 0, True, "inactive", None),
        (True, 0, False, "unknown", None),
        (False, 0, False, "unknown", None),
    ],
)
def test_routability_disable_and_untriggered_enable(requested, rounds, completed, status, actual):
    report = _report(
        "place.routability_opt",
        requested,
        {"routability_opt_flag": requested},
        {
            "place_object_count": 1,
            "routability_branch_round_count": rounds,
            "placement_completed": completed,
        },
        succeeded=completed,
    )
    assert (report["status"], report["actual_value"]) == (status, actual)


def test_tool_disabled_flag_does_not_fulfill_enable_request():
    report = _report(
        "place.routability_opt",
        value=True,
        params={"routability_opt_flag": False},
        probe={
            "place_object_count": 1,
            "routability_branch_round_count": 0,
            "placement_completed": True,
        },
    )
    assert (report["status"], report["actual_value"]) == ("inactive", None)


@pytest.mark.parametrize(
    "written,sites,status",
    [
        (400, 1, "effective"),
        (0, 0, "effective"),
        (400, 0, "inactive"),
    ],
)
def test_padding_uses_sites_and_distinguishes_deliberate_zero(written, sites, status):
    report = _report(
        "place.cell_padding_x",
        written,
        {},
        {"cell_padding": {"padding_sites": sites, "geometry_apply_count": 1}},
    )
    assert (report["status"], report["actual_value"]) == (status, sites)
    assert report["written_value"] == written


def test_padding_capture_converts_before_database_scaling():
    recorder = DreamplaceRecorder({"knob_id": "place.cell_padding_x", "value": 400})
    placedb = SimpleNamespace(site_width=200, cell_padding_x=0)

    def apply(db, _params):
        db.cell_padding_x = 200

    _observe_cell_padding(recorder, apply, placedb, SimpleNamespace(cell_padding_x=400))
    assert recorder.probe["cell_padding"] == {"padding_sites": 1, "geometry_apply_count": 1}


def test_density_weight_uses_coefficient_not_internal_tensor():
    recorder = DreamplaceRecorder({"knob_id": "place.density_weight", "value": 0.001})
    model = SimpleNamespace(
        op_collections=SimpleNamespace(),
        initialize_density_weight=lambda _params, _db: [0.004, 0.005],
    )
    params = SimpleNamespace(density_weight=0.001)
    with ExitStack() as stack:
        _observe_native_model(model, recorder, stack)
        assert model.initialize_density_weight(params, None) == [0.004, 0.005]
    report = _report("place.density_weight", 0.001, {}, recorder.probe, succeeded=False)
    assert (report["status"], report["actual_value"]) == ("effective", 0.001)
    assert report["observation"] == {"configured_density_weight": 0.001, "initialization_count": 1}


@pytest.mark.parametrize(
    "knob,value", [("floorplan.core_util", 0.8), ("floorplan.aspect_ratio", 1.0)]
)
@pytest.mark.parametrize("mode,status", [("die_util", "effective"), ("die_size", "inactive")])
def test_floorplan_actual_is_input_not_geometry(tmp_path, knob, value, mode, status):
    config = tmp_path / "fp.json"
    config.write_text(
        json.dumps(
            {"die_builder": {"mode": mode, "die_util": {"utilization": 0.8, "aspect_ratio": 1.0}}}
        )
    )
    feature = tmp_path / "feature.json"
    feature.write_text(
        json.dumps(
            {
                "Design Layout": {
                    "core_usage": 0.79,
                    "core_bounding_width": 40.0,
                    "core_bounding_height": 20.0,
                }
            }
        )
    )
    report = build_floorplan_report(
        {"knob_id": knob, "value": value},
        {
            "config_path": str(config),
            "init_fp_call_count": 1,
            "run_fp_call_count": 1,
            "run_fp_completed": True,
        },
        feature,
        engine_succeeded=False,
    )
    assert (report["status"], report["actual_value"]) == (
        status,
        value if mode == "die_util" else None,
    )


def test_scoped_method_restored_and_ignores_other_threads():
    class Owner:
        def run(self):
            return "original"

    original = Owner.run
    with ExitStack() as stack:
        _patch_method(stack, Owner, "run", lambda wrapped, owner: (wrapped(owner), "observed"))
        assert Owner().run() == ("original", "observed")
        results = []
        thread = Thread(target=lambda: results.append(Owner().run()))
        thread.start()
        thread.join()
        assert results == ["original"]
    assert Owner.run is original


def test_scoped_callable_preserves_operator_methods():
    class Operation:
        def __call__(self):
            return "original"

        def reset(self):
            return "reset"

    owner = SimpleNamespace(density_op=Operation())
    original = owner.density_op
    with ExitStack() as stack:
        _patch_method(stack, owner, "density_op", lambda wrapped: (wrapped(), "observed"))
        assert owner.density_op() == ("original", "observed")
        assert owner.density_op.reset() == "reset"
    assert owner.density_op is original


def test_report_failure_does_not_change_tool_result(monkeypatch, tmp_path):
    failures = []
    workspace = SimpleNamespace(
        directory=tmp_path,
        logger=SimpleNamespace(exception=lambda message: failures.append(message)),
    )

    def fail_write(*_args, **_kwargs):
        raise OSError("read-only analysis directory")

    monkeypatch.setattr("agent.data.parameter_runtime_observer.write_json_atomic", fail_write)
    assert _invoke_and_record(workspace, lambda: True, lambda _ok: {}) is True
    assert failures == ["Failed to persist parameter runtime evidence"]
