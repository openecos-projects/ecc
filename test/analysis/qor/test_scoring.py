import pytest

from chipcompiler.analysis.qor.dimensions import evaluate_dimensions
from chipcompiler.analysis.qor.feasibility import evaluate_feasibility
from chipcompiler.analysis.qor.features import compute_features
from chipcompiler.analysis.qor.scoring import PROFILES, evaluate_scalar_summary
from test.analysis.qor.helpers import gcd_corners, gcd_metrics, make_inputs


def _summary(inputs):
    bundle = compute_features(inputs)
    dimensions = evaluate_dimensions(bundle, inputs)
    feasibility = evaluate_feasibility(inputs)
    return evaluate_scalar_summary(feasibility, dimensions, inputs.profile), dimensions


class TestScalarSummary:
    def test_spec_reference_gcd_projection(self):
        # Spec §12.1 with the D-C place ladder: all four evaluated dims
        # renormalize over weights (0.30+0.25+0.15+0.15)/0.85.
        summary, _ = _summary(make_inputs(gcd_metrics(), corners=gcd_corners(), tclk_ns=20.0))
        assert summary.score == pytest.approx(98.96, abs=0.01)
        assert summary.status == "GREEN"

    def test_spec_reference_weighted_mean_formula(self):
        # Pin the documented §12.1 weighted-mean formula itself:
        # (0.30*100 + 0.25*75.434 + 0.15*100 + 0.15*94.105) / 0.85 = 91.7.
        weights = PROFILES["balanced"]
        score = (
            weights["timing"] * 100.0
            + weights["interconnect"] * 75.434
            + weights["area"] * 100.0
            + weights["robustness"] * 94.105
        ) / (weights["timing"] + weights["interconnect"] + weights["area"] + weights["robustness"])
        assert score == pytest.approx(91.7, abs=0.05)

    def test_physical_fail_vetoes_to_zero(self):
        metrics = gcd_metrics()
        metrics["drc_count"].value = 1
        summary, dimensions = _summary(make_inputs(metrics, tclk_ns=20.0))
        assert summary.score == 0.0
        assert summary.status == "FAIL"
        # Excellent other dimensions cannot mask the failure.
        assert dimensions["area"].value == pytest.approx(100.0)

    def test_not_verified_is_not_rated(self):
        states = {step: "Success" for step in ("Synthesis", "Floorplan", "place", "CTS", "route")}
        states["drc"] = "Unstart"
        summary, _ = _summary(make_inputs(gcd_metrics(), states))
        assert summary.score is None
        assert summary.status == "NOT_RATED"

    def test_missing_dimensions_renormalize(self):
        # Robustness (no corners, no CTS depths) and power (no budget)
        # evaluate to null while all signoff gates pass; the remaining
        # weights renormalize instead of compressing the score scale.
        metrics = {
            metric_id: record
            for metric_id, record in gcd_metrics().items()
            if not metric_id.startswith(("clock_path_", "cts_buffer", "cts_inverter"))
        }
        summary, _ = _summary(make_inputs(metrics, tclk_ns=20.0))
        assert summary.score == pytest.approx(100.0)
        assert summary.status == "GREEN"

    def test_profile_weights_change_ranking(self):
        base = make_inputs(gcd_metrics(), corners=gcd_corners(), tclk_ns=20.0)
        bundle = compute_features(base)
        dimensions = evaluate_dimensions(bundle, base)
        feasibility = evaluate_feasibility(base)
        balanced = evaluate_scalar_summary(feasibility, dimensions, "balanced").score
        critical = evaluate_scalar_summary(feasibility, dimensions, "timing_critical").score
        # All-evaluated-dimensions-near-100 keeps both high; timing_critical
        # weights its 100-score timing dimension higher than balanced does.
        assert critical >= balanced

    def test_unknown_profile_falls_back_to_balanced(self):
        inputs = make_inputs(gcd_metrics(), corners=gcd_corners(), tclk_ns=20.0)
        bundle = compute_features(inputs)
        dimensions = evaluate_dimensions(bundle, inputs)
        feasibility = evaluate_feasibility(inputs)
        summary = evaluate_scalar_summary(feasibility, dimensions, "nonexistent")
        assert summary.profile == "nonexistent"
        assert summary.weights == PROFILES["balanced"]
