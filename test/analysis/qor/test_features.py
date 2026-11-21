import pytest

from chipcompiler.analysis.qor.features import compute_features
from test.analysis.qor.helpers import make_inputs, make_metric


def test_leakage_fraction_handles_zero_dynamic_power():
    inputs = make_inputs(
        {
            "synthesis_power_dynamic_uw": make_metric("synthesis_power_dynamic_uw", 0.0),
            "synthesis_power_leakage_uw": make_metric("synthesis_power_leakage_uw", 5.0),
        }
    )
    feature = compute_features(inputs).features["F_SYN_LEAK_FRAC"]
    assert feature.value == 1.0


def test_frequency_margin_is_emitted_as_diagnostic_feature():
    inputs = make_inputs(
        {"sta_setup_wns": make_metric("sta_setup_wns", 0.1)},
        tclk_ns=1.0,
    )
    feature = compute_features(inputs).features["F_STA_FREQ_MARGIN"]
    assert feature.value is not None
    assert feature.state == "OPPORTUNITY"


def test_power_analysis_leakage_fraction_uses_signoff_metrics():
    inputs = make_inputs(
        {
            "power_analysis_dynamic_uw": make_metric(
                "power_analysis_dynamic_uw", 59.6078, step="power_analysis"
            ),
            "power_analysis_leakage_uw": make_metric(
                "power_analysis_leakage_uw", 1.6772, step="power_analysis"
            ),
        }
    )

    feature = compute_features(inputs).features["F_PWR_LEAK_FRAC"]

    assert feature.value == pytest.approx(0.02737, abs=1e-5)
    assert feature.input_metric_ids == [
        "power_analysis_dynamic_uw",
        "power_analysis_leakage_uw",
    ]


def test_power_analysis_leakage_fraction_reads_current_metric_ids():
    inputs = make_inputs(
        {
            "power_analysis_dynamic_uw": make_metric(
                "power_analysis_dynamic_uw", 8.0, step="power_analysis"
            ),
            "power_analysis_leakage_uw": make_metric(
                "power_analysis_leakage_uw", 2.0, step="power_analysis"
            ),
        }
    )

    feature = compute_features(inputs).features["F_PWR_LEAK_FRAC"]

    assert feature.value == pytest.approx(0.2)
    assert feature.input_metric_ids == [
        "power_analysis_dynamic_uw",
        "power_analysis_leakage_uw",
    ]


def test_egr_overflow_gcell_fraction_is_size_normalized():
    inputs = make_inputs(egr_gcell_count=2000, egr_overflowed_gcell_count=5)
    feature = compute_features(inputs).supplementary["F_PL_EGR_OVERFLOW_GCELL_FRAC"]
    assert feature.value == pytest.approx(0.0025)
    assert feature.unit == "ratio"


def test_egr_overflow_gcell_fraction_unknown_without_grid():
    feature = compute_features(make_inputs()).supplementary["F_PL_EGR_OVERFLOW_GCELL_FRAC"]
    assert feature.value is None
    assert feature.state == "UNKNOWN"


def test_tns_fep_and_hold_margin_features_are_published():
    inputs = make_inputs(
        {
            "sta_setup_wns": make_metric("sta_setup_wns", -0.2),
            "sta_setup_tns": make_metric("sta_setup_tns", -5.0),
            "sta_hold_tns": make_metric("sta_hold_tns", -0.5),
            "sta_hold_wns": make_metric("sta_hold_wns", -0.05),
            "sta_setup_violation_count": make_metric("sta_setup_violation_count", 12),
            "sta_hold_violation_count": make_metric("sta_hold_violation_count", 0),
        },
        tclk_ns=2.0,
    )
    published = compute_features(inputs).supplementary
    assert published["F_STA_SETUP_TNS"].value == -5.0
    assert published["F_STA_SETUP_TNS"].unit == "ns"
    assert published["F_STA_HOLD_TNS"].value == -0.5
    assert published["F_STA_SETUP_TNS_NORM"].value == pytest.approx(-2.5)
    assert published["F_STA_SETUP_FEP"].value == 12
    assert published["F_STA_SETUP_FEP"].state == "FAIL"
    assert published["F_STA_HOLD_FEP"].state == "PASS"
    assert published["F_STA_HOLD_HEADROOM"].value == pytest.approx(-0.025)
    assert published["F_STA_HOLD_HEADROOM"].state == "FAIL"


def test_supplementary_features_are_unknown_when_metrics_missing():
    published = compute_features(make_inputs(tclk_ns=1.0)).supplementary
    assert all(feature.value is None for feature in published.values())
    assert all(feature.state == "UNKNOWN" for feature in published.values())
