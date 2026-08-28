from __future__ import annotations

import json
from types import SimpleNamespace

from chipcompiler.tools.ecc_dreamplace.module import (
    _observe_native_model,
    _write_parameter_runtime_report,
)


class _Scalar:
    def __init__(self, value):
        self.value = value

    def item(self):
        return self.value


def _engine(*, target_density=None, cell_padding_x=None):
    data_collections = SimpleNamespace(target_density=_Scalar(target_density))
    return SimpleNamespace(
        placer=SimpleNamespace(data_collections=data_collections),
        placedb=SimpleNamespace(cell_padding_x=cell_padding_x, num_movable_nodes=12),
    )


def test_runtime_report_records_native_density_consumer(tmp_path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "candidate_materialization.v1.json").write_text(
        json.dumps({"patch": [{"knob_id": "place.target_density", "value": 0.85}]}),
        encoding="utf-8",
    )
    params = SimpleNamespace(target_density=0.85)
    _write_parameter_runtime_report(
        SimpleNamespace(directory=tmp_path),
        params,
        engine=_engine(target_density=0.85),
        ppa={"iteration": 3},
        engine_succeeded=True,
    )
    report = json.loads((analysis / "parameter_runtime_report.v1.json").read_text())
    assert report["activation"]["status"] == "used"
    assert report["activation"]["consumers"][0]["consumer_id"] == "dreamplace.density_objective"
    assert report["consumer_observation"] == {
        "density_tensor_value": 0.85,
        "effective_target_density": 0.85,
        "evidence_complete": True,
        "placement_iteration_count": 3,
        "requested_target_density": 0.85,
    }


def test_runtime_report_records_density_utilization_floor_transition(tmp_path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "candidate_materialization.v1.json").write_text(
        json.dumps({"patch": [{"knob_id": "place.target_density", "value": 0.2}]}),
        encoding="utf-8",
    )

    _write_parameter_runtime_report(
        SimpleNamespace(directory=tmp_path),
        SimpleNamespace(target_density=0.8),
        engine=_engine(target_density=0.8),
        ppa={"iteration": 4},
        engine_succeeded=True,
    )

    report = json.loads((analysis / "parameter_runtime_report.v1.json").read_text())
    assert report["effective_initial"] == {"unit": "ratio", "value": 0.8}
    assert report["transitions"] == [
        {
            "evidence_ref": "analysis/parameter_runtime_report.v1.json",
            "evidence_sha256": report["activation"]["consumers"][0]["evidence_sha256"],
            "from": "materialized",
            "reason": "DREAMPlace utilization lower bound",
            "rule_id": "dreamplace.target_density.utilization_floor",
            "sequence": 0,
            "to": "overridden",
            "value": 0.8,
        }
    ]


def test_runtime_report_does_not_parse_logged_parameter_values(tmp_path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "candidate_materialization.v1.json").write_text(
        json.dumps({"patch": [{"knob_id": "place.target_density", "value": 0.85}]}),
        encoding="utf-8",
    )
    log_dir = tmp_path / "place_dreamplace" / "log"
    log_dir.mkdir(parents=True)
    (log_dir / "place.log").write_text("parameters = {'target_density': 0.2}\n", encoding="utf-8")

    _write_parameter_runtime_report(
        SimpleNamespace(directory=tmp_path),
        SimpleNamespace(target_density=0.85),
        engine=_engine(target_density=0.85),
        ppa={"iteration": 2},
        engine_succeeded=True,
    )

    report = json.loads((analysis / "parameter_runtime_report.v1.json").read_text())
    assert report["effective_final"]["value"] == 0.85


def test_runtime_report_uses_objective_weight_unit(tmp_path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "candidate_materialization.v1.json").write_text(
        json.dumps({"patch": [{"knob_id": "place.density_weight", "value": 0.001}]}),
        encoding="utf-8",
    )
    _write_parameter_runtime_report(
        SimpleNamespace(directory=tmp_path),
        SimpleNamespace(density_weight=0.001),
        engine=SimpleNamespace(
            native_runtime_probe={
                "density_weight_initializations": [0.004],
                "density_weight_updates": [{"sequence": 0, "before": 0.004, "after": 0.006}],
            }
        ),
        ppa={"iteration": 5, "objective": 12.5},
        engine_succeeded=True,
    )
    report = json.loads((analysis / "parameter_runtime_report.v1.json").read_text())
    assert report["effective_initial"]["unit"] == "objective_weight"
    assert report["effective_final"]["unit"] == "objective_weight"
    assert report["consumer_observation"] == {
        "configured_density_weight": 0.001,
        "density_weight_update_count": 1,
        "density_weight_updates": [{"after": 0.006, "before": 0.004, "sequence": 0}],
        "evidence_complete": True,
        "final_objective": 12.5,
        "final_internal_density_weight": 0.006,
        "internal_initial_density_weight": 0.004,
        "placement_iteration_count": 5,
    }


def test_runtime_report_records_overflow_predicate_evaluation(tmp_path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "candidate_materialization.v1.json").write_text(
        json.dumps({"patch": [{"knob_id": "place.target_overflow", "value": 0.1}]}),
        encoding="utf-8",
    )

    _write_parameter_runtime_report(
        SimpleNamespace(directory=tmp_path),
        SimpleNamespace(stop_overflow=0.1),
        engine=SimpleNamespace(metrics={"overflow": [0.7, _Scalar(0.12), 0.08]}),
        ppa={"iteration": 7, "overflow": 0.08},
        engine_succeeded=True,
    )

    report = json.loads((analysis / "parameter_runtime_report.v1.json").read_text())
    assert report["activation"]["status"] == "used"
    assert report["activation"]["consumers"][0]["outcome"] == "evaluated"
    assert report["consumer_observation"] == {
        "comparison_count": 3,
        "effective_stop_overflow": 0.1,
        "evidence_complete": True,
        "final_overflow": 0.08,
        "minimum_observed_overflow": 0.08,
        "placement_iteration_count": 7,
        "threshold_reached": True,
    }


def test_runtime_report_preserves_consumed_cell_padding_after_restore(tmp_path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "candidate_materialization.v1.json").write_text(
        json.dumps({"patch": [{"knob_id": "place.cell_padding_x", "value": 400}]}),
        encoding="utf-8",
    )

    _write_parameter_runtime_report(
        SimpleNamespace(directory=tmp_path),
        SimpleNamespace(cell_padding_x=0),
        engine=_engine(target_density=0.8, cell_padding_x=200),
        ppa={"iteration": 3},
        engine_succeeded=True,
    )

    report = json.loads((analysis / "parameter_runtime_report.v1.json").read_text())
    assert report["effective_initial"] == {"unit": "dbu", "value": 200}
    assert report["activation"]["status"] == "used"
    assert report["consumer_observation"] == {
        "effective_padding_dbu": 200,
        "evidence_complete": True,
        "movable_node_count": 12,
        "placement_iteration_count": 3,
        "requested_padding_site": 400,
    }


def test_runtime_report_marks_disabled_routability_not_activated(tmp_path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "candidate_materialization.v1.json").write_text(
        json.dumps({"patch": [{"knob_id": "place.routability_opt", "value": False}]}),
        encoding="utf-8",
    )
    _write_parameter_runtime_report(
        SimpleNamespace(directory=tmp_path),
        SimpleNamespace(routability_opt_flag=False),
        engine=SimpleNamespace(),
        ppa={"iteration": 3},
    )
    report = json.loads((analysis / "parameter_runtime_report.v1.json").read_text())
    assert report["activation"]["status"] == "not_activated"


def test_runtime_report_requires_a_native_routability_round(tmp_path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "candidate_materialization.v1.json").write_text(
        json.dumps({"patch": [{"knob_id": "place.routability_opt", "value": True}]}),
        encoding="utf-8",
    )
    _write_parameter_runtime_report(
        SimpleNamespace(directory=tmp_path),
        SimpleNamespace(routability_opt_flag=True),
        engine=SimpleNamespace(),
        ppa={"iteration": 3},
        engine_succeeded=True,
    )
    report = json.loads((analysis / "parameter_runtime_report.v1.json").read_text())
    assert report["activation"]["status"] == "unknown"
    assert report["consumer_observation"]["evidence_complete"] is False

    log_dir = tmp_path / "place_dreamplace" / "log"
    log_dir.mkdir(parents=True)
    (log_dir / "place.log").write_text(
        "routability optimization round 0: adjust area flags = (1, 1, 0)\n",
        encoding="utf-8",
    )
    _write_parameter_runtime_report(
        SimpleNamespace(directory=tmp_path),
        SimpleNamespace(routability_opt_flag=True),
        engine=SimpleNamespace(native_runtime_probe={"routability_branch_round_count": 1}),
        ppa={"iteration": 3},
        engine_succeeded=True,
    )
    report = json.loads((analysis / "parameter_runtime_report.v1.json").read_text())
    assert report["activation"]["status"] == "used"
    assert report["consumer_observation"]["branch_round_count"] == 1


def test_runtime_report_binds_producer_revision_and_source(tmp_path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "candidate_materialization.v1.json").write_text(
        json.dumps({"patch": [{"knob_id": "place.target_density", "value": 0.85}]}),
        encoding="utf-8",
    )

    _write_parameter_runtime_report(
        SimpleNamespace(directory=tmp_path),
        SimpleNamespace(target_density=0.85),
        engine=_engine(target_density=0.85),
        ppa={"iteration": 2},
        engine_succeeded=True,
    )

    report = json.loads((analysis / "parameter_runtime_report.v1.json").read_text())
    assert report["tool"]["name"] == "DREAMPlace"
    assert report["tool"]["revision"] == "ecc.dreamplace.parameter_runtime_report.v2"
    assert report["tool"]["source_sha256"].startswith("sha256:")
    assert len(report["tool"]["source_sha256"]) == 71


def test_native_probe_observes_density_updates_and_routability_calls():
    probe = {
        "density_weight_initializations": [],
        "density_weight_updates": [],
        "routability_branch_round_count": 0,
    }
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

    _observe_native_model(model, probe)

    assert model.initialize_density_weight() == 0.004
    assert model.op_collections.update_density_weight_op() == "updated"
    assert model.op_collections.adjust_node_area_op() == "adjusted"
    assert probe == {
        "density_weight_initializations": [0.004],
        "density_weight_updates": [{"sequence": 0, "before": 0.004, "after": 0.006}],
        "routability_branch_round_count": 1,
    }


def test_runtime_report_does_not_claim_use_before_engine_success(tmp_path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (analysis / "candidate_materialization.v1.json").write_text(
        json.dumps({"patch": [{"knob_id": "place.target_density", "value": 0.2}]}),
        encoding="utf-8",
    )
    _write_parameter_runtime_report(
        SimpleNamespace(directory=tmp_path),
        SimpleNamespace(target_density=0.8),
        engine=_engine(target_density=0.8),
        ppa={"iteration": 3},
    )
    report = json.loads((analysis / "parameter_runtime_report.v1.json").read_text())
    assert report["activation"] == {"status": "unknown", "consumers": []}
    assert report["transitions"] == []
