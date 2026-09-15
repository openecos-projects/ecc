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
