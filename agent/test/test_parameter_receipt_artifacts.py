from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.data.candidate_artifacts import sha256_path
from agent.data.candidate_materialization import (
    CandidateMaterializationError,
    materialize_candidate_config,
)
from agent.data.parameter_application_receipt import build_parameter_application_receipt
from agent.workspace_api import (
    _candidate_parameter_receipt,
    _parameter_receipt_context,
    _stable_hash,
)
from chipcompiler.runtime.workspace_api import RuntimeApiError

HASH = "sha256:" + "a" * 64
PRODUCER = Path(__file__).parents[2] / "chipcompiler/tools/ecc_dreamplace/module.py"
TOOL = {
    "name": "DREAMPlace",
    "revision": "ecc.dreamplace.parameter_runtime_report.v2",
    "source_sha256": sha256_path(PRODUCER),
}


def _write_unknown_runtime_report(analysis: Path, *, knob_id: str, requested_value: object) -> None:
    (analysis / "parameter_runtime_report.v1.json").write_text(
        json.dumps(
            {
                "knob_id": knob_id,
                "requested_value": requested_value,
                "tool": TOOL,
                "application_status": "unknown",
                "activation": {"status": "unknown", "consumers": []},
                "effective_initial": {"value": None, "unit": "ratio"},
                "effective_final": {"value": None, "unit": "ratio"},
            }
        ),
        encoding="utf-8",
    )


def _materialized_workspace(
    tmp_path: Path,
    *,
    candidate_id: str,
    knob_id: str,
    before: object,
    written: object,
) -> tuple[SimpleNamespace, Path]:
    tech = tmp_path / "pdk" / "prtech" / "techLEF" / "N551P6M_ecos.lef"
    tech.parent.mkdir(parents=True)
    tech.write_text(
        "UNITS\n  DATABASE MICRONS 1000 ;\nEND UNITS\nSITE core7\n  SIZE 0.2 BY 1.4 ;\nEND core7\n",
        encoding="utf-8",
    )
    origin = tmp_path / "origin"
    (origin / "rtl").mkdir(parents=True)
    (origin / "rtl" / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
    (origin / "constraints.sdc").write_text("create_clock clk\n", encoding="utf-8")
    (origin / "filelist.f").write_text("rtl/top.v\n", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    (home / "parameters.json").write_text(
        json.dumps({"PDK Root": str(tmp_path / "pdk")}),
        encoding="utf-8",
    )
    config = tmp_path / "config" / "dreamplace.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({knob_id.removeprefix("place."): before}), encoding="utf-8")
    workspace = SimpleNamespace(
        directory=tmp_path,
        config={"dreamplace": config},
        pdk=SimpleNamespace(tech=tech, site_core="core7"),
        flow=SimpleNamespace(data={"steps": [{"name": "place", "tool": "dreamplace"}]}),
    )
    materialize_candidate_config(
        workspace,
        "place",
        [{"knob_id": knob_id, "value": written}],
        candidate_id,
    )
    return workspace, tmp_path / "analysis" / "candidate_materialization.v1.json"


def test_candidate_parameter_receipt_is_written_atomically(tmp_path: Path) -> None:
    workspace, materialization = _materialized_workspace(
        tmp_path,
        candidate_id="candidate-1",
        knob_id="place.target_density",
        before=0.5,
        written=0.85,
    )
    analysis = tmp_path / "analysis"
    _write_unknown_runtime_report(
        analysis,
        knob_id="place.target_density",
        requested_value=0.85,
    )
    request = SimpleNamespace(
        candidate_id="candidate-1",
        target_step="place",
        patch=[{"knob_id": "place.target_density", "value": 0.85}],
        context_sha256=HASH,
        seed=17,
    )

    receipt = _candidate_parameter_receipt(
        workspace,
        request,
        ".agent/candidates/candidate-1",
        materialization,
        parent_flow_sha256=HASH,
    )

    receipt_path = analysis / "parameter_application_receipt.v1.json"
    assert receipt_path.is_file()
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == receipt
    assert sha256_path(receipt_path) is not None
    assert receipt["tool"] == TOOL
    materialization_ref = receipt["materialization"]
    assert materialization_ref["target_step"] == "place"
    assert materialization_ref["config_ref"] == "config/dreamplace.json"
    assert materialization_ref["before_snapshot_ref"].endswith("dreamplace.before.json")
    assert materialization_ref["after_snapshot_ref"].endswith("dreamplace.after.json")
    assert materialization_ref["receipt_sha256"] != materialization_ref["registry_sha256"]


def test_parameter_receipt_context_aggregates_all_rtl_and_sdc_files(tmp_path: Path) -> None:
    workspace, _ = _materialized_workspace(
        tmp_path,
        candidate_id="candidate-multifile",
        knob_id="place.target_density",
        before=0.5,
        written=0.85,
    )
    origin = tmp_path / "origin"
    (origin / "rtl" / "worker.v").write_text("module worker; endmodule\n", encoding="utf-8")
    (origin / "timing.sdc").write_text("set_input_delay 1 clk\n", encoding="utf-8")
    (origin / "filelist.f").write_text("rtl/top.v\nrtl/worker.v\n", encoding="utf-8")
    request = SimpleNamespace(
        candidate_id="candidate-multifile",
        target_step="place",
        patch=[{"knob_id": "place.target_density", "value": 0.85}],
        seed=17,
    )

    context = _parameter_receipt_context(workspace, request, HASH)

    rtl_sha256 = _stable_hash(
        {"files": [sha256_path(path) for path in sorted((origin / "rtl").glob("*"))]}
    )
    sdc_sha256 = _stable_hash(
        {"files": [sha256_path(path) for path in sorted(origin.glob("*.sdc"))]}
    )
    filelist_sha256 = sha256_path(origin / "filelist.f")
    assert context["rtl_sha256"] == rtl_sha256
    assert context["sdc_sha256"] == sdc_sha256
    assert context["design_sha256"] == _stable_hash(
        {
            "rtl_sha256": rtl_sha256,
            "filelist_sha256": filelist_sha256,
            "sdc_sha256": sdc_sha256,
        }
    )


def test_cell_padding_receipt_preserves_surface_site_value(tmp_path: Path, monkeypatch) -> None:
    workspace, materialization = _materialized_workspace(
        tmp_path,
        candidate_id="candidate-padding",
        knob_id="place.cell_padding_x",
        before=0,
        written=1,
    )
    request = SimpleNamespace(
        candidate_id="candidate-padding",
        target_step="place",
        patch=[{"knob_id": "place.cell_padding_x", "value": 1}],
        context_sha256=HASH,
        seed=17,
    )
    monkeypatch.setattr(
        "agent.workspace_api._parameter_receipt_context",
        lambda *_args: {"site_width_dbu": 200},
    )
    _write_unknown_runtime_report(
        tmp_path / "analysis",
        knob_id="place.cell_padding_x",
        requested_value=200,
    )
    receipt = _candidate_parameter_receipt(
        workspace,
        request,
        ".agent/candidates/candidate-padding",
        materialization,
        parent_flow_sha256="sha256:" + "0" * 64,
    )
    assert receipt["requested"] == {"knob_id": "place.cell_padding_x", "value": 1, "unit": "site"}
    assert receipt["materialization"]["written_value"] == 200
    assert receipt["materialization"]["unit"] == "dbu"


def test_candidate_parameter_receipt_rejects_incomplete_l1(tmp_path: Path) -> None:
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    materialization = analysis / "candidate_materialization.v1.json"
    materialization.write_text(
        json.dumps({"patch": [{"knob_id": "place.target_density", "value": 0.85}]}),
        encoding="utf-8",
    )
    request = SimpleNamespace(
        candidate_id="candidate-1",
        target_step="place",
        patch=[{"knob_id": "place.target_density", "value": 0.85}],
        context_sha256=HASH,
        seed=17,
    )

    with pytest.raises(CandidateMaterializationError):
        _candidate_parameter_receipt(
            SimpleNamespace(directory=tmp_path),
            request,
            ".agent/candidates/candidate-1",
            materialization,
            parent_flow_sha256=HASH,
        )


def test_candidate_receipt_preserves_native_consumer_observation_and_transition(
    tmp_path: Path,
) -> None:
    workspace, materialization = _materialized_workspace(
        tmp_path,
        candidate_id="candidate-floor",
        knob_id="place.target_density",
        before=0.5,
        written=0.2,
    )
    analysis = tmp_path / "analysis"
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
                "knob_id": "place.target_density",
                "requested_value": 0.2,
                "tool": TOOL,
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
        context_sha256=HASH,
        seed=17,
    )

    receipt = _candidate_parameter_receipt(
        workspace,
        request,
        ".agent/candidates/candidate-floor",
        materialization,
        parent_flow_sha256=HASH,
    )

    assert receipt["consumer_observation"] == observation
    assert receipt["transitions"] == [transition]


def test_candidate_parameter_receipt_rejects_runtime_report_for_another_knob(
    tmp_path: Path,
) -> None:
    workspace, materialization = _materialized_workspace(
        tmp_path,
        candidate_id="candidate-density",
        knob_id="place.target_density",
        before=0.5,
        written=0.85,
    )
    (tmp_path / "analysis" / "parameter_runtime_report.v1.json").write_text(
        json.dumps(
            {
                "knob_id": "place.density_weight",
                "requested_value": 0.001,
                "tool": TOOL,
                "application_status": "applied",
                "effective_initial": {"value": 0.001, "unit": "objective_weight"},
                "effective_final": {"value": 0.001, "unit": "objective_weight"},
                "activation": {
                    "status": "used",
                    "consumers": [
                        {
                            "consumer_id": "dreamplace.density_preconditioner",
                            "outcome": "entered",
                            "evidence_ref": "analysis/parameter_runtime_report.v1.json",
                            "evidence_sha256": HASH,
                        }
                    ],
                },
                "consumer_observation": {"evidence_complete": True},
                "transitions": [],
            }
        ),
        encoding="utf-8",
    )
    request = SimpleNamespace(
        candidate_id="candidate-density",
        target_step="place",
        patch=[{"knob_id": "place.target_density", "value": 0.85}],
        context_sha256=HASH,
        seed=17,
    )

    with pytest.raises(RuntimeApiError, match="runtime report"):
        _candidate_parameter_receipt(
            workspace,
            request,
            ".agent/candidates/candidate-density",
            materialization,
            parent_flow_sha256=HASH,
        )


def test_candidate_parameter_receipt_requires_parent_flow_sha256(
    tmp_path: Path,
) -> None:
    workspace, materialization = _materialized_workspace(
        tmp_path,
        candidate_id="candidate-no-parent",
        knob_id="place.target_density",
        before=0.5,
        written=0.85,
    )
    _write_unknown_runtime_report(
        tmp_path / "analysis",
        knob_id="place.target_density",
        requested_value=0.85,
    )
    request = SimpleNamespace(
        candidate_id="candidate-no-parent",
        target_step="place",
        patch=[{"knob_id": "place.target_density", "value": 0.85}],
        context_sha256=HASH,
        seed=17,
    )

    with pytest.raises(RuntimeApiError, match="parent flow"):
        _candidate_parameter_receipt(
            workspace,
            request,
            ".agent/candidates/candidate-no-parent",
            materialization,
        )


def test_candidate_parameter_receipt_rejects_stripped_unknown_ecc_revision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace, materialization = _materialized_workspace(
        tmp_path,
        candidate_id="candidate-unknown-revision",
        knob_id="place.target_density",
        before=0.5,
        written=0.85,
    )
    _write_unknown_runtime_report(
        tmp_path / "analysis",
        knob_id="place.target_density",
        requested_value=0.85,
    )
    request = SimpleNamespace(
        candidate_id="candidate-unknown-revision",
        target_step="place",
        patch=[{"knob_id": "place.target_density", "value": 0.85}],
        context_sha256=HASH,
        seed=17,
    )
    monkeypatch.setattr("agent.workspace_api.chipcompiler.__version__", " unknown ")

    with pytest.raises(RuntimeApiError, match="ECC revision"):
        _candidate_parameter_receipt(
            workspace,
            request,
            ".agent/candidates/candidate-unknown-revision",
            materialization,
            parent_flow_sha256=HASH,
        )


def test_parameter_receipt_rejects_unbound_tool_metadata() -> None:
    with pytest.raises(ValueError, match="tool metadata"):
        build_parameter_application_receipt(
            receipt_id="parameter-receipt-1",
            tool={"name": "DREAMPlace", "revision": "bound"},
            context={"stage": "place"},
            requested={"knob_id": "place.target_density", "value": 0.85, "unit": "ratio"},
            materialization={},
            runtime_report={"activation": {"status": "unknown", "consumers": []}},
        )
