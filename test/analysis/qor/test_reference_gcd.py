"""End-to-end regression against the reference GCD fixture (spec §12.1).

The spec's headline numbers assume route-side compatibility, which the
D-C ladder downgrades to the I_place path until the toolchain emits net
mappings. This test pins the ladder values end-to-end, and pins the
spec's own I_total-based numbers on the calibration layer (see
test_scoring.test_spec_reference_weighted_mean_formula).
"""

import json
import os
from dataclasses import replace
from types import SimpleNamespace

import pytest

from chipcompiler.analysis.qor import (
    build_qor_analysis,
    refresh_workspace_qor_report,
    render_qor_analysis,
)
from chipcompiler.analysis.qor.loader import load_workspace_qor_inputs
from chipcompiler.analysis.qor.models import PowerObservation
from chipcompiler.analysis.qor.schema import validate_report

SUCCESS = "Success"

_FLOW_STEPS = {
    "Synthesis": SUCCESS,
    "Floorplan": SUCCESS,
    "place": SUCCESS,
    "CTS": SUCCESS,
    "route": SUCCESS,
    "drc": SUCCESS,
    "lvs": SUCCESS,
    "RCX": SUCCESS,
    "sta": SUCCESS,
    "Harden": SUCCESS,
}


def _write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f)


def _metric(metric_id, value, project_role="final", unit=""):
    return {
        "id": metric_id,
        "display_name": metric_id,
        "value": value,
        "unit": unit,
        "category": "timing",
        "direction": "lower_is_better",
        "scope": "project",
        "corner": None,
        "project_role": project_role,
        "step_role": "primary",
        "rating": {"gate": False, "score": True, "trend": True},
        "source": {"kind": "analysis", "path": "feature", "selector": "/x"},
    }


def _payload(metrics):
    return {
        "schema_version": 3,
        "kind": "qor_metrics",
        "integrity": {"status": "pass", "invalid_metric_source_ids": [], "invalid_detail_ids": []},
        "metrics": metrics,
    }


def _make_gcd_workspace(tmp_path):
    root = str(tmp_path / "ws")
    _write(
        os.path.join(root, "home", "flow.json"),
        {
            "steps": [
                {"name": name, "tool": "ecc", "state": state} for name, state in _FLOW_STEPS.items()
            ]
        },
    )
    _write(
        os.path.join(root, "home", "parameters.json"),
        {"Design": "gcd", "frequency_max": 50.0},
    )

    directory_by_step = {
        "Synthesis": "Synthesis_yosys",
        "Floorplan": "Floorplan_ecc",
        "place": "place_dreamplace",
        "CTS": "CTS_ecc",
        "route": "route_ecc",
        "drc": "drc_ecc",
        "lvs": "lvs_ecc",
        "RCX": "RCX_ecc",
        "sta": "sta_ecc",
        "Harden": "Harden_ecc",
    }
    payloads = {
        "Synthesis": [_metric("synthesis_cell_area", 800.0, "trend", "um^2")],
        "Floorplan": [
            _metric("core_area", 1538.46, "trend", "um^2"),
            _metric("core_utilization", 0.52, "trend"),
        ],
        "place": [
            _metric("place_hpwl", 3143.52, "trend", "um"),
            _metric("place_grwl", 3812.00, "trend", "um"),
            _metric("place_rudy_utilization_max", 0.0, "trend"),
        ],
        "CTS": [
            _metric("cts_buffer_count", 4, "trend"),
            _metric("cts_inverter_count", 0, "trend"),
            _metric("clock_path_max_buffer", 4, "trend"),
            _metric("clock_path_min_buffer", 4, "trend"),
        ],
        "route": [
            _metric("route_wirelength", 4315.53, "final", "um"),
            _metric("route_via_count", 608, "final"),
        ],
        "drc": [_metric("drc_count", 0, "gate")],
        "lvs": [_metric("lvs_count", 0, "gate")],
        "RCX": [
            _metric("rcx_spef_file_count", 2, "gate"),
            _metric("rcx_expected_corner_count", 2, "trend"),
            _metric("rcx_missing_corner_count", 0, "gate"),
        ],
        "sta": [
            _metric("sta_setup_wns", 16.622, "gate", "ns"),
            _metric("sta_setup_tns", 0.0, "gate", "ns"),
            _metric("sta_hold_wns", 0.1, "gate", "ns"),
            _metric("sta_hold_tns", 0.0, "gate", "ns"),
            _metric("sta_setup_violation_count", 0, "gate"),
            _metric("sta_hold_violation_count", 0, "gate"),
            _metric("sta_expected_corner_count", 2, "trend"),
            _metric("sta_missing_corner_count", 0, "gate"),
        ],
        "Harden": [_metric("harden_artifact_missing_count", 0, "final")],
    }
    for step_value, metrics in payloads.items():
        _write(
            os.path.join(root, directory_by_step[step_value], "analysis", "qor_metrics.json"),
            _payload(metrics),
        )

    for corner_dir, setup_wns, hold_wns in (
        ("MAX_125_t125", 16.622, 0.100),
        ("MAX_M40_tm40", 18.980, 0.274),
    ):
        _write(
            os.path.join(root, "sta_ecc", "feature", corner_dir, "Cworst", "qor_summary.json"),
            {
                "path_groups": [],
                "summary": {
                    "setup": {"wns": setup_wns, "tns": 0.0, "nvp": 0, "frequency_mhz": 296.0},
                    "hold": {"wns": hold_wns, "tns": 0.0, "nvp": 0},
                },
            },
        )

    class _Flow:
        data = {}

    return SimpleNamespace(
        directory=root, name="gcd", design=SimpleNamespace(name="gcd"), flow=_Flow()
    )


class TestReferenceGcd:
    @pytest.fixture
    def analysis(self, tmp_path):
        return build_qor_analysis(_make_gcd_workspace(tmp_path))

    def test_feasibility_passes_all_gates(self, analysis):
        assert analysis.feasibility.status == "PASS"
        assert all(gate.state == "passed" for gate in analysis.feasibility.gates)
        assert len(analysis.feasibility.gates) == 7

    def test_evidence_is_high(self, analysis):
        assert analysis.evidence.state == "HIGH"
        assert analysis.evidence.index == pytest.approx(100.0)

    def test_qt_spec_value(self, analysis):
        # WS = +16.622ns >= tau_guardband (0.05*20ns) -> QT = 100, OPPORTUNITY.
        assert analysis.qor_record["timing"].value == pytest.approx(100.0)
        assert analysis.qor_record["timing"].state == "OPPORTUNITY"

    def test_qi_place_ladder_value(self, analysis):
        # I_place = 3812/3143.52 = 1.2127 <= tau_pref = 1.25, S_cong = 0.
        assert analysis.inflation.i_place == pytest.approx(1.2127, abs=0.001)
        assert analysis.qor_record["interconnect"].value == pytest.approx(100.0)

    def test_route_side_stays_unknown_under_dc_ladder(self, analysis):
        assert analysis.inflation.i_route is None
        assert analysis.inflation.i_total is None
        assert analysis.inflation.compatibility_status == "INCOMPATIBLE"

    def test_qa_and_qp_spec_values(self, analysis):
        assert analysis.qor_record["area"].value == pytest.approx(100.0)
        assert analysis.qor_record["power"].value is None

    def test_qr_spec_value(self, analysis):
        assert analysis.qor_record["robustness"].value == pytest.approx(94.105, abs=0.01)

    def test_scalar_summary_ladder_value(self, analysis):
        # (0.30*100 + 0.25*100 + 0.15*100 + 0.15*94.105) / 0.85 = 98.96.
        assert analysis.scalar_summary.score == pytest.approx(98.96, abs=0.01)
        assert analysis.scalar_summary.status == "GREEN"

    def test_over_provision_diagnosis_present(self, analysis):
        over = next(
            d for d in analysis.diagnoses if d.diagnosis_id == "diag.timing.over_provisioned"
        )
        assert over.state == "OPPORTUNITY"
        assert over.severity == pytest.approx(0.789, abs=0.001)

    def test_report_persists_and_validates(self, tmp_path):
        workspace = _make_gcd_workspace(tmp_path)
        destination = refresh_workspace_qor_report(workspace)
        assert destination.name == "qor_report.json"
        with open(destination) as f:
            payload = json.load(f)
        assert payload["schema_version"] == 3
        assert payload["scoring_engine"] == "qor-v3"
        assert validate_report(payload) == []
        assert payload["flow_steps"]["sta"] == "Success"

    def test_renderer_matches_spec_layout(self, tmp_path):
        workspace = _make_gcd_workspace(tmp_path)
        analysis = build_qor_analysis(workspace)
        text = render_qor_analysis(analysis, load_workspace_qor_inputs(workspace))
        assert "ECC QoR ANALYSIS REPORT" in text
        assert "FEASIBILITY STATUS : PASS [All 7 Physical Signoff Gates Clean]" in text
        assert "EVIDENCE STATE     : HIGH" in text
        assert "Status: GREEN, Profile: balanced" in text
        assert "Q_T" in text
        assert "WS: +16.622ns" in text
        assert "[PRIORITIZED INTERVENTION HYPOTHESES]" in text
        assert "diag.timing.over_provisioned" in text

    def test_renderer_includes_observed_power_without_budget(self, analysis):
        report = replace(
            analysis,
            power=PowerObservation(
                total_uw=12_400.0,
                budget_uw=None,
                source_path="/ws/sta_ecc/feature/MAX_125/Cworst/power_summary.json",
                source_kind="signoff",
                corner="MAX_125/Cworst",
            ),
        )
        text = render_qor_analysis(report)
        assert "Ptotal: 0.012W; no budget declared" in text
