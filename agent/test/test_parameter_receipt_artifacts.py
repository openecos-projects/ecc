from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agent.data.candidate_artifacts import sha256_path
from agent.workspace_api import _candidate_parameter_receipt


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
