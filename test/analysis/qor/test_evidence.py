import pytest

from chipcompiler.analysis.qor.evidence import evaluate_evidence
from chipcompiler.analysis.qor.features import compute_features
from test.analysis.qor.helpers import gcd_metrics, make_inputs


def _evidence(inputs):
    bundle = compute_features(inputs)
    return evaluate_evidence(inputs, bundle)


class TestEvidenceIndex:
    def test_complete_evidence_is_high(self):
        evidence = _evidence(make_inputs(gcd_metrics(), corners=[], tclk_ns=20.0))
        assert evidence.state == "HIGH"
        assert evidence.index == pytest.approx(100.0)

    def test_no_analyzed_steps_is_not_verified(self):
        evidence = _evidence(make_inputs())
        assert evidence.index is None
        assert evidence.state == "NOT_VERIFIED"

    def test_parse_failures_degrade_integrity(self):
        inputs = make_inputs(gcd_metrics())
        inputs.parse_failures = 1
        inputs.analyzed_steps = list(inputs.analyzed_steps)
        evidence = _evidence(inputs)
        assert evidence.integrity == pytest.approx(0.0)
        assert evidence.state == "INSUFFICIENT"

    def test_invalid_selectors_reduce_integrity(self):
        inputs = make_inputs(gcd_metrics())
        inputs.analyzed_steps = ["sta", "route"]
        inputs.invalid_selector_count = 1
        evidence = _evidence(inputs)
        assert evidence.integrity == pytest.approx(1.0 - 1 / 2)

    def test_missing_sta_corners_degrade_coverage(self):
        metrics = gcd_metrics()
        metrics["sta_missing_corner_count"].value = 1
        evidence = _evidence(make_inputs(metrics))
        # STA loads 1/2; RCX loads 2/2 -> coverage averages to 0.75.
        assert evidence.coverage == pytest.approx(0.75)
        assert evidence.state == "MODERATE"

    def test_consistency_c2_detects_ws_nvp_contradiction(self):
        metrics = gcd_metrics()
        metrics["sta_setup_wns"].value = -0.5  # WS < 0 but NVP == 0
        evidence = _evidence(make_inputs(metrics))
        # C1 drops out (INCOMPATIBLE), C2 fails, C3 passes.
        assert evidence.consistency == pytest.approx(0.5)

    def test_consistency_c1_not_applicable_when_incompatible(self):
        evidence = _evidence(make_inputs(gcd_metrics()))
        # Route side is INCOMPATIBLE (CTS ran), so C1 drops out.
        assert evidence.consistency == pytest.approx(1.0)

    def test_zero_expected_corners_is_not_a_division_error(self):
        metrics = gcd_metrics()
        for metric_id in ("sta_expected_corner_count", "sta_missing_corner_count"):
            metrics[metric_id].value = 0
        evidence = _evidence(make_inputs(metrics))
        assert evidence.coverage == pytest.approx(1.0)  # RCX-only coverage
