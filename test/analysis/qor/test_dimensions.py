import pytest

from chipcompiler.analysis.qor.calibration import TAU_AREA_FAIL, psi_cost
from chipcompiler.analysis.qor.dimensions import evaluate_dimensions
from chipcompiler.analysis.qor.features import compute_features
from test.analysis.qor.helpers import gcd_corners, gcd_metrics, make_inputs, make_metric


def _dimensions(inputs):
    bundle = compute_features(inputs)
    return bundle, evaluate_dimensions(bundle, inputs)


class TestTimingQuality:
    def test_positive_margins_differentiate(self):
        # +50ps of a 1ns clock (5% guardband) reaches full credit.
        _, dims = _dimensions(
            make_inputs({"sta_setup_wns": make_metric("sta_setup_wns", 0.05)}, tclk_ns=1.0)
        )
        assert dims["timing"].value == pytest.approx(100.0)

    def test_small_positive_margin_is_partial(self):
        _, dims = _dimensions(
            make_inputs({"sta_setup_wns": make_metric("sta_setup_wns", 0.025)}, tclk_ns=1.0)
        )
        assert dims["timing"].value == pytest.approx(75.0)

    def test_zero_slack_is_fifty(self):
        _, dims = _dimensions(
            make_inputs({"sta_setup_wns": make_metric("sta_setup_wns", 0.0)}, tclk_ns=1.0)
        )
        assert dims["timing"].value == pytest.approx(50.0)
        assert dims["timing"].state == "WATCH"

    def test_negative_slack_scores_below_fifty_and_fails(self):
        _, dims = _dimensions(
            make_inputs({"sta_setup_wns": make_metric("sta_setup_wns", -0.1)}, tclk_ns=1.0)
        )
        assert 0.0 <= dims["timing"].value < 50.0
        assert dims["timing"].state == "FAIL"

    def test_monotone_in_signed_slack(self):
        values = []
        for ws in (-0.2, -0.1, 0.0, 0.01, 0.05, 0.2):
            _, dims = _dimensions(
                make_inputs({"sta_setup_wns": make_metric("sta_setup_wns", ws)}, tclk_ns=1.0)
            )
            values.append(dims["timing"].value)
        assert values == sorted(values)

    def test_missing_tclk_is_unknown_not_zero(self):
        _, dims = _dimensions(make_inputs({"sta_setup_wns": make_metric("sta_setup_wns", 0.5)}))
        assert dims["timing"].value is None
        assert dims["timing"].state == "UNKNOWN"


class TestInterconnectQuality:
    def test_place_ladder_under_preferred_threshold_is_full_credit(self):
        # GCD ladder: I_place = 3812/3143.52 = 1.213 <= tau_pref, S_cong small.
        _, dims = _dimensions(make_inputs(gcd_metrics(), tclk_ns=20.0))
        assert dims["interconnect"].value == pytest.approx(100.0)

    def test_qi_matches_spec_calibration_for_itotal(self):
        # Pin the spec §12.1 calibration point: I_total=1.373, S_cong=0.
        assert 100.0 * psi_cost(1.373, 1.25, 1.75) == pytest.approx(75.4, abs=0.1)

    def test_congestion_multiplier_applies(self):
        metrics = gcd_metrics()
        metrics["place_rudy_utilization_max"].value = 2.0  # S_cong >= 1 -> zero credit
        _, dims = _dimensions(make_inputs(metrics, tclk_ns=20.0))
        assert dims["interconnect"].value == pytest.approx(0.0)


class TestAreaQuality:
    def test_target_interval_full_credit(self):
        _, dims = _dimensions(make_inputs(gcd_metrics(), tclk_ns=20.0))
        assert dims["area"].value == pytest.approx(100.0)

    def test_over_utilization_fails_at_fail_bound(self):
        metrics = gcd_metrics()
        metrics["core_utilization"].value = TAU_AREA_FAIL
        _, dims = _dimensions(make_inputs(metrics))
        assert dims["area"].value == pytest.approx(0.0)
        assert dims["area"].state == "FAIL"

    def test_under_utilization_penalized(self):
        metrics = gcd_metrics()
        metrics["core_utilization"].value = 0.225
        _, dims = _dimensions(make_inputs(metrics))
        assert dims["area"].value == pytest.approx(50.0)

    def test_missing_utilization_is_unknown(self):
        metrics = gcd_metrics()
        del metrics["core_utilization"]
        _, dims = _dimensions(make_inputs(metrics))
        assert dims["area"].value is None
        assert dims["area"].state == "UNKNOWN"


class TestPowerQuality:
    def test_no_budget_is_unknown_not_zero(self):
        _, dims = _dimensions(make_inputs(gcd_metrics()))
        assert dims["power"].value is None
        assert dims["power"].state == "UNKNOWN"

    def test_budget_operating_points(self):
        metrics = gcd_metrics()
        for total, expected in ((0.0, 100.0), (500.0, 50.0), (1000.0, 0.0), (1500.0, 0.0)):
            inputs = make_inputs(metrics, power_budget_uw=1000.0, power_total_uw=total)
            bundle = compute_features(inputs)
            dims = evaluate_dimensions(bundle, inputs)
            assert dims["power"].value == pytest.approx(expected), total


class TestRobustnessQuality:
    def test_spec_reference_value(self):
        # QR = 100*(1 - [0.5*0 + 0.5*(2.358/20)]) = 94.105 (spec §12.1).
        _, dims = _dimensions(make_inputs(gcd_metrics(), corners=gcd_corners(), tclk_ns=20.0))
        assert dims["robustness"].value == pytest.approx(94.105, abs=0.01)

    def test_missing_pvt_renormalizes_to_cts_weight(self):
        metrics = gcd_metrics()
        metrics["clock_path_max_buffer"].value = 5
        metrics["clock_path_min_buffer"].value = 1
        _, dims = _dimensions(make_inputs(metrics, tclk_ns=20.0))
        # imbalance = (5-1)/5 = 0.8; the single contributor renormalizes to w=1.
        assert dims["robustness"].value == pytest.approx(20.0)

    def test_missing_both_contributors_is_unknown(self):
        metrics = gcd_metrics()
        del metrics["clock_path_max_buffer"]
        del metrics["clock_path_min_buffer"]
        _, dims = _dimensions(make_inputs(metrics))
        assert dims["robustness"].value is None
        assert dims["robustness"].state == "UNKNOWN"
