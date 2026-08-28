from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agent.data.candidate_artifacts import sha256_path
from agent.workspace_api import _candidate_parameter_receipt

HASH = "sha256:" + "a" * 64


def test_candidate_parameter_receipt_is_written_atomically(tmp_path: Path) -> None:
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    materialization = analysis / "candidate_materialization.v1.json"
    materialization.write_text(
        json.dumps(
            {
                "patch": [{"knob_id": "place.target_density", "value": 0.85}],
                "configs": [{}],
            }
        ),
        encoding="utf-8",
    )
    request = SimpleNamespace(
        candidate_id="candidate-1",
        target_step="place",
        patch=[{"knob_id": "place.target_density", "value": 0.85}],
    )

    receipt = _candidate_parameter_receipt(
        SimpleNamespace(directory=tmp_path),
        request,
        ".agent/candidates/candidate-1",
        materialization,
    )

    receipt_path = analysis / "parameter_application_receipt.v1.json"
    assert receipt_path.is_file()
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == receipt
    assert sha256_path(receipt_path) is not None


def test_cell_padding_receipt_preserves_surface_site_value(tmp_path: Path, monkeypatch) -> None:
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    materialization = analysis / "candidate_materialization.v1.json"
    materialization.write_text(
        json.dumps(
            {
                "patch": [{"knob_id": "place.cell_padding_x", "value": 200}],
                "configs": [{}],
            }
        ),
        encoding="utf-8",
    )
    request = SimpleNamespace(
        candidate_id="candidate-padding",
        target_step="place",
        patch=[{"knob_id": "place.cell_padding_x", "value": 200}],
    )
    monkeypatch.setattr(
        "agent.workspace_api._parameter_receipt_context",
        lambda *_args: {"site_width_dbu": 200},
    )
    receipt = _candidate_parameter_receipt(
        SimpleNamespace(directory=tmp_path),
        request,
        ".agent/candidates/candidate-padding",
        materialization,
        parent_flow_sha256="sha256:" + "0" * 64,
    )
    assert receipt["requested"] == {"knob_id": "place.cell_padding_x", "value": 1, "unit": "site"}


def test_candidate_receipt_preserves_native_consumer_observation_and_transition(
    tmp_path: Path,
) -> None:
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    materialization = analysis / "candidate_materialization.v1.json"
    materialization.write_text(
        json.dumps({"patch": [{"knob_id": "place.target_density", "value": 0.2}], "configs": [{}]}),
        encoding="utf-8",
    )
    observation = {
        "requested_target_density": 0.2,
        "effective_target_density": 0.8,
        "density_tensor_value": 0.8,
        "placement_iteration_count": 4,
        "evidence_complete": True,
    }
    transition = {
        "sequence": 0,
        "from": "materialized",
        "to": "overridden",
        "value": 0.8,
        "reason": "DREAMPlace utilization lower bound",
        "rule_id": "dreamplace.target_density.utilization_floor",
        "evidence_ref": "analysis/parameter_runtime_report.v1.json",
        "evidence_sha256": HASH,
    }
    (analysis / "parameter_runtime_report.v1.json").write_text(
        json.dumps(
            {
                "application_status": "applied",
                "effective_initial": {"value": 0.8, "unit": "ratio"},
                "effective_final": {"value": 0.8, "unit": "ratio"},
                "activation": {
                    "status": "used",
                    "consumers": [
                        {
                            "consumer_id": "dreamplace.density_objective",
                            "outcome": "entered",
                            "evidence_ref": "analysis/parameter_runtime_report.v1.json",
                            "evidence_sha256": HASH,
                        }
                    ],
                },
                "consumer_observation": observation,
                "transitions": [transition],
            }
        ),
        encoding="utf-8",
    )
    request = SimpleNamespace(
        candidate_id="candidate-floor",
        target_step="place",
        patch=[{"knob_id": "place.target_density", "value": 0.2}],
    )

    receipt = _candidate_parameter_receipt(
        SimpleNamespace(directory=tmp_path),
        request,
        ".agent/candidates/candidate-floor",
        materialization,
    )

    assert receipt["consumer_observation"] == observation
    assert receipt["transitions"] == [transition]
