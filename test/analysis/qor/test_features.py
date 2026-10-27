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
                "power_analysis_dynamic_uw", 59.6078, step="powerAnalysis"
            ),
            "power_analysis_leakage_uw": make_metric(
                "power_analysis_leakage_uw", 1.6772, step="powerAnalysis"
            ),
        }
    )

    feature = compute_features(inputs).features["F_PWR_LEAK_FRAC"]

    assert feature.value == pytest.approx(0.02737, abs=1e-5)
    assert feature.input_metric_ids == [
        "power_analysis_dynamic_uw",
        "power_analysis_leakage_uw",
    ]


def test_power_analysis_leakage_fraction_reads_legacy_metric_ids():
    inputs = make_inputs(
        {
            "synthesis_power_dynamic_uw": make_metric(
                "synthesis_power_dynamic_uw", 8.0, step="powerAnalysis"
            ),
            "synthesis_power_leakage_uw": make_metric(
                "synthesis_power_leakage_uw", 2.0, step="powerAnalysis"
            ),
        }
    )

    feature = compute_features(inputs).features["F_PWR_LEAK_FRAC"]

    assert feature.value == pytest.approx(0.2)
    assert feature.input_metric_ids == [
        "synthesis_power_dynamic_uw",
        "synthesis_power_leakage_uw",
    ]
