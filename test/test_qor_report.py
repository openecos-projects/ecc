import json
import os
from types import SimpleNamespace

import pytest

from chipcompiler.engine.qor_report import build_qor_report, generate_qor_report
from chipcompiler.engine.signoff.report_checklist import (
    build_checklist_report,
    generate_checklist_report,
)


def _write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f)


def _metric(metric_id, value, project_role="final", **overrides):
    record = {
        "id": metric_id,
        "display_name": metric_id,
        "value": value,
        "unit": "",
        "category": "timing",
        "direction": "lower_is_better",
        "scope": "project",
        "corner": None,
        "project_role": project_role,
        "step_role": "primary",
        "rating": {"gate": False, "score": True, "trend": True},
        "source": {"kind": "analysis", "path": "x"},
    }
    record.update(overrides)
    return record


def _metrics_payload(metrics):
    return {
        "schema_version": 3,
        "kind": "qor_metrics",
        "metrics": metrics,
    }


def _make_workspace(tmp_path, *, with_metrics=True, with_checklist=True):
    root = tmp_path / "ws"
    _write(
        root / "home" / "flow.json",
        {
            "steps": [
                {"name": "Synthesis", "tool": "yosys", "state": "Success"},
                {"name": "Floorplan", "tool": "ecc", "state": "Success"},
                {"name": "place", "tool": "dreamplace", "state": "Success"},
                {"name": "CTS", "tool": "ecc", "state": "Success"},
                {"name": "route", "tool": "ecc", "state": "Success"},
                {"name": "drc", "tool": "ecc", "state": "Success"},
                {"name": "lvs", "tool": "ecc", "state": "Success"},
                {"name": "RCX", "tool": "ecc", "state": "Success"},
                {"name": "sta", "tool": "ecc", "state": "Success"},
                {"name": "Harden", "tool": "ecc", "state": "Success"},
            ]
        },
    )
    _write(root / "home" / "parameters.json", {"Design": "gcd", "frequency_max": 50.0})
    if with_metrics:
        _write(
            root / "drc_ecc" / "analysis" / "qor_metrics.json",
            _metrics_payload([_metric("drc_count", 0, "gate")]),
        )
        _write(
            root / "lvs_ecc" / "analysis" / "qor_metrics.json",
            _metrics_payload([_metric("lvs_count", 0, "gate")]),
        )
        _write(
            root / "RCX_ecc" / "analysis" / "qor_metrics.json",
            _metrics_payload(
                [
                    _metric("rcx_spef_file_count", 1, "gate"),
                    _metric("rcx_expected_corner_count", 1, "trend"),
                    _metric("rcx_missing_corner_count", 0, "gate"),
                ]
            ),
        )
        _write(
            root / "sta_ecc" / "analysis" / "qor_metrics.json",
            _metrics_payload(
                [
                    _metric("sta_setup_wns", 0.05, "gate", unit="ns"),
                    _metric("sta_setup_tns", 0.0, "gate", unit="ns"),
                    _metric("sta_hold_wns", 0.02, "gate", unit="ns"),
                    _metric("sta_hold_tns", 0.0, "gate", unit="ns"),
                    _metric("sta_setup_violation_count", 0, "gate"),
                    _metric("sta_hold_violation_count", 0, "gate"),
                    _metric("sta_expected_corner_count", 1, "trend"),
                    _metric("sta_missing_corner_count", 0, "gate"),
                ]
            ),
        )
        _write(
            root / "Harden_ecc" / "analysis" / "qor_metrics.json",
            _metrics_payload([_metric("harden_artifact_missing_count", 0, "final")]),
        )
    if with_checklist:
        _write(
            root / "home" / "checklist.json",
            {
                "schema_version": 3,
                "kind": "signoff_checklist",
                "checker_revision": "signoff-v1",
                "generated_at": "2026-01-01T00:00:00Z",
                "status": "attention",
                "summary": {"passed": 2, "blocked": 1, "attention": 1, "unavailable": 0},
                "checklist": [
                    {
                        "id": "flow.route",
                        "step": "route",
                        "category": "flow",
                        "title": "Routing complete",
                        "policy": "block",
                        "state": "pass",
                        "blocked": False,
                        "summary": "ok",
                        "source": {},
                        "evidence": [],
                    },
                    {
                        "id": "quality.drc.clean",
                        "step": "drc",
                        "category": "quality",
                        "title": "DRC clean",
                        "policy": "block",
                        "state": "failed",
                        "blocked": True,
                        "summary": "drc_count=2 (required == 0)",
                        "source": {},
                        "evidence": [
                            {"kind": "feature", "path": "drc_ecc/analysis/qor_summary.json"}
                        ],
                    },
                    {
                        "id": "harden.gds",
                        "step": "Harden",
                        "category": "artifact",
                        "title": "Harden GDS",
                        "policy": "warn",
                        "state": "warning",
                        "blocked": False,
                        "summary": "optional file missing",
                        "source": {},
                        "evidence": [],
                    },
                    {
                        "id": "sta.corner",
                        "step": "sta",
                        "category": "quality",
                        "title": "Corner coverage",
                        "policy": "block",
                        "state": "pass",
                        "blocked": False,
                        "summary": "",
                        "source": {},
                        "evidence": [],
                    },
                ],
            },
        )

    class _Flow:
        def __init__(self, data):
            self.data = data

    with open(root / "home" / "flow.json") as f:
        flow_data = json.load(f)

    return SimpleNamespace(
        directory=str(root),
        name="gcd",
        design=SimpleNamespace(name="gcd"),
        flow=_Flow(flow_data),
    )


class TestBuildQorReport:
    def test_clean_workspace_rates_continuous_quality(self, tmp_path):
        # This fixture carries signoff-passing metrics only: timing is the
        # sole evaluated quality coordinate. WS=+0.05ns of a 20ns clock
        # reaches the 1ns guardband, so QT = 52.5 and the projection is
        # RED — honest, since no area/interconnect/robustness evidence
        # exists and weights renormalize over {timing} alone.
        report = build_qor_report(_make_workspace(tmp_path))
        assert report.feasibility.status == "PASS"
        by_key = {dim.key: dim for dim in report.dimension_scores}
        assert by_key["timing"].value == pytest.approx(52.5)
        assert by_key["timing"].state == "WATCH"
        assert report.overall_score == pytest.approx(52.5)
        assert report.scalar_summary.status == "RED"

    def test_dimension_scores_carry_the_five_coordinates(self, tmp_path):
        report = build_qor_report(_make_workspace(tmp_path))
        assert {dim.key for dim in report.dimension_scores} == {
            "timing",
            "interconnect",
            "area",
            "power",
            "robustness",
        }
        # No placed area or power budget in this fixture: they stay UNKNOWN.
        by_key = {dim.key: dim for dim in report.dimension_scores}
        assert by_key["power"].value is None
        assert by_key["power"].state == "UNKNOWN"

    def test_stale_metrics_of_unstarted_steps_do_not_score(self, tmp_path):
        workspace = _make_workspace(tmp_path)
        for step in workspace.flow.data["steps"]:
            if step["name"] == "drc":
                step["state"] = "Unstart"

        report = build_qor_report(workspace)

        assert report.feasibility.status == "NOT_VERIFIED"
        drc_gate = next(g for g in report.feasibility.gates if g.id == "GATE_DRC")
        assert drc_gate.state == "unavailable"
        assert drc_gate.availability == "not_verified"

    def test_signoff_failure_vetoes_the_score(self, tmp_path):
        workspace = _make_workspace(tmp_path)
        _write(
            os.path.join(workspace.directory, "drc_ecc", "analysis", "qor_metrics.json"),
            _metrics_payload([_metric("drc_count", 2, "gate")]),
        )
        report = build_qor_report(workspace)
        assert report.feasibility.status == "PHYSICAL_FAIL"
        assert report.overall_score == 0.0
        assert report.scalar_summary.status == "FAIL"

    def test_empty_workspace_report(self, tmp_path):
        # Steps completed per the ledger but no payloads survived: that is
        # corrupt/missing evidence (UNKNOWN), not an omitted verification.
        report = build_qor_report(_make_workspace(tmp_path, with_metrics=False))
        assert report.overall_score is None
        assert report.scalar_summary.status == "NOT_RATED"
        assert report.feasibility.status == "UNKNOWN"
        text = generate_qor_report(_make_workspace(tmp_path, with_metrics=False))
        assert "NOT_RATED" in text
        assert "UNKNOWN" in text

    def test_missing_evidence_of_completed_stage_is_unknown(self, tmp_path):
        workspace = _make_workspace(tmp_path)
        _write(
            os.path.join(workspace.directory, "lvs_ecc", "analysis", "qor_metrics.json"),
            {"broken": True},
        )
        report = build_qor_report(workspace)
        assert report.feasibility.status == "UNKNOWN"
        lvs_gate = next(g for g in report.feasibility.gates if g.id == "GATE_LVS")
        assert lvs_gate.availability == "corrupt"

    def test_uses_loaded_workspace_parameters(self, tmp_path):
        workspace = _make_workspace(tmp_path)
        workspace.name = ""
        workspace.design = SimpleNamespace(name="")
        workspace.parameters = SimpleNamespace(data={"design": "from_params"})

        assert build_qor_report(workspace).design == "from_params"

    def test_text_report_layout(self, tmp_path):
        text = generate_qor_report(_make_workspace(tmp_path))
        assert "ECC QoR ANALYSIS REPORT" in text
        assert "FEASIBILITY STATUS" in text
        assert "EVIDENCE STATE" in text
        assert "QoR COMPOSITE" in text
        assert "[PHYSICAL QoR RECORD BREAKDOWN]" in text
        assert "[PRIORITIZED INTERVENTION HYPOTHESES]" in text
        assert "(No active feasibility blockers detected)" in text


class TestChecklistReport:
    def test_build_from_checklist_json(self, tmp_path):
        report = build_checklist_report(_make_workspace(tmp_path))
        assert report.available is True
        assert report.status == "attention"
        assert len(report.items) == 4
        assert len(report.blocked_items) == 1
        assert report.blocked_items[0].id == "quality.drc.clean"
        assert len(report.attention_items) == 1

    def test_unavailable_when_missing(self, tmp_path):
        report = build_checklist_report(_make_workspace(tmp_path, with_checklist=False))
        assert report.available is False

    def test_text_report(self, tmp_path):
        text = generate_checklist_report(_make_workspace(tmp_path))
        assert "ECC SIGNOFF CHECKLIST REPORT" in text
        assert "ATTENTION" in text
        assert "quality.drc.clean" not in text  # table shows titles, not ids
        assert "DRC clean" in text
        assert "evidence: drc_ecc/analysis/qor_summary.json" in text
        assert "END OF CHECKLIST REPORT" in text

    def test_unavailable_text(self, tmp_path):
        text = generate_checklist_report(_make_workspace(tmp_path, with_checklist=False))
        assert "Checklist unavailable" in text
