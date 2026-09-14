import pytest

from chipcompiler.analysis.qor.diagnosis import build_diagnoses
from chipcompiler.analysis.qor.dimensions import evaluate_dimensions
from chipcompiler.analysis.qor.feasibility import evaluate_feasibility
from chipcompiler.analysis.qor.features import compute_features
from chipcompiler.analysis.qor.interventions import prioritize
from test.analysis.qor.helpers import gcd_corners, gcd_metrics, make_inputs


def _diagnoses(inputs):
    bundle = compute_features(inputs)
    dimensions = evaluate_dimensions(bundle, inputs)
    feasibility = evaluate_feasibility(inputs)
    return build_diagnoses(feasibility, dimensions, bundle, inputs)


class TestGateSeverity:
    def test_signoff_failures_are_tier_one_and_above_bottlenecks(self):
        metrics = gcd_metrics()
        metrics["drc_count"].value = 1
        diagnoses = _diagnoses(make_inputs(metrics, tclk_ns=20.0))
        signoff = next(d for d in diagnoses if d.diagnosis_id.startswith("diag.signoff"))
        assert signoff.severity >= 0.80
        non_signoff = [d for d in diagnoses if not d.diagnosis_id.startswith("diag.signoff")]
        assert all(d.severity < 0.80 for d in non_signoff)

    def test_violation_magnitude_preserves_ordering(self):
        mild = gcd_metrics()
        mild["sta_setup_wns"].value = -0.001
        severe = gcd_metrics()
        severe["sta_setup_wns"].value = -2.5
        mild_severity = next(
            d
            for d in _diagnoses(make_inputs(mild, tclk_ns=20.0))
            if d.diagnosis_id == "diag.signoff.gate_setup_slack"
        ).severity
        severe_severity = next(
            d
            for d in _diagnoses(make_inputs(severe, tclk_ns=20.0))
            if d.diagnosis_id == "diag.signoff.gate_setup_slack"
        ).severity
        assert severe_severity > mild_severity
        # tau_timing_fail = 0.20 * 20ns = 4ns: (-2.5)/4 = 0.625 magnitude.
        assert severe_severity == pytest.approx(0.80 + 0.20 * 0.625)
        assert mild_severity == pytest.approx(0.80, abs=0.01)

    def test_clean_design_has_no_fail_diagnoses(self):
        diagnoses = _diagnoses(make_inputs(gcd_metrics(), corners=gcd_corners(), tclk_ns=20.0))
        assert all(d.state != "FAIL" for d in diagnoses)


class TestQualityAndOpportunityDiagnoses:
    def test_over_provisioned_timing_is_opportunity(self):
        diagnoses = _diagnoses(make_inputs(gcd_metrics(), corners=gcd_corners(), tclk_ns=20.0))
        over = next(d for d in diagnoses if d.diagnosis_id == "diag.timing.over_provisioned")
        assert over.state == "OPPORTUNITY"
        # (16.622 - 4.0) / (20.0 - 4.0) = 0.789 (spec eq. 57).
        assert over.severity == pytest.approx(0.789, abs=0.001)
        assert over.interventions[0].tier == "TIER_3_OPPORTUNITY"

    def test_bottleneck_below_threshold_reports_watch(self):
        metrics = gcd_metrics()
        metrics["core_utilization"].value = 0.40  # area quality 88.9 -> no
        metrics["place_rudy_utilization_max"].value = 1.5  # S_cong = 1.5
        diagnoses = _diagnoses(make_inputs(metrics, tclk_ns=20.0))
        congestion = next(d for d in diagnoses if d.diagnosis_id == "diag.place.congestion")
        assert congestion.severity == pytest.approx(1.0)
        assert congestion.state == "WATCH"

    def test_non_causal_language(self):
        metrics = gcd_metrics()
        metrics["drc_count"].value = 2
        for diagnosis in _diagnoses(make_inputs(metrics, tclk_ns=20.0)):
            text = diagnosis.interpretation.lower()
            assert "caused" not in text
            assert "proves" not in text

    def test_prioritization_is_tier_lexicographic(self):
        metrics = gcd_metrics()
        metrics["drc_count"].value = 5
        diagnoses = _diagnoses(make_inputs(metrics, corners=gcd_corners(), tclk_ns=20.0))
        ranked = prioritize(diagnoses)
        tier_rank = {"TIER_1_FEASIBILITY": 0, "TIER_2_BOTTLENECK": 1, "TIER_3_OPPORTUNITY": 2}
        tiers = [intervention.tier for intervention in ranked]
        assert tiers == sorted(tiers, key=lambda tier: tier_rank[tier])
