from chipcompiler.analysis.qor.feasibility import evaluate_feasibility
from chipcompiler.analysis.qor.loader import CornerSlack
from test.analysis.qor.helpers import gcd_metrics, make_inputs

ALL_SUCCESS = {
    step: "Success"
    for step in (
        "synthesis",
        "post_floorplan",
        "placement",
        "cts",
        "routing",
        "drc",
        "lvs",
        "rcx",
        "sta",
        "harden",
    )
}


def _status(inputs):
    return evaluate_feasibility(inputs).status


class TestFeasibilityReduction:
    def test_clean_signoff_passes(self):
        assert _status(make_inputs(gcd_metrics(), ALL_SUCCESS)) == "PASS"

    def test_any_failed_gate_vetoes_everything(self):
        metrics = gcd_metrics()
        metrics["drc_count"].value = 3
        inputs = make_inputs(metrics, ALL_SUCCESS)
        feasibility = evaluate_feasibility(inputs)
        assert feasibility.status == "PHYSICAL_FAIL"
        failed = [gate for gate in feasibility.gates if gate.state == "failed"]
        assert [gate.id for gate in failed] == ["GATE_DRC"]

    def test_negative_setup_slack_fails(self):
        metrics = gcd_metrics()
        metrics["sta_setup_wns"].value = -0.25
        assert _status(make_inputs(metrics, ALL_SUCCESS)) == "PHYSICAL_FAIL"

    def test_missing_stage_is_not_verified_never_fail(self):
        # An omitted verification stage must not become a physical failure.
        states = dict(ALL_SUCCESS)
        states["drc"] = "Unstart"
        assert _status(make_inputs(gcd_metrics(), states)) == "NOT_VERIFIED"

    def test_completed_stage_with_missing_evidence_is_unknown(self):
        metrics = gcd_metrics()
        del metrics["drc_count"]
        assert _status(make_inputs(metrics, ALL_SUCCESS)) == "UNKNOWN"

    def test_failure_outranks_missing_evidence(self):
        metrics = gcd_metrics()
        metrics["drc_count"].value = 1
        del metrics["lvs_count"]  # completed stage, corrupt evidence
        assert _status(make_inputs(metrics, ALL_SUCCESS)) == "PHYSICAL_FAIL"

    def test_hold_gate_uses_signed_worst_slack(self):
        metrics = gcd_metrics()
        metrics["sta_hold_wns"].value = -0.01
        inputs = make_inputs(metrics, ALL_SUCCESS)
        feasibility = evaluate_feasibility(inputs)
        hold = next(gate for gate in feasibility.gates if gate.id == "GATE_HOLD_SLACK")
        assert hold.state == "failed"
        assert hold.timing_slack.wns_ns == -0.01
        assert hold.timing_slack.ws_ns == -0.01

    def test_setup_slack_gate_carries_signed_and_clamped_views(self):
        inputs = make_inputs(gcd_metrics(), ALL_SUCCESS)
        setup = next(
            gate for gate in evaluate_feasibility(inputs).gates if gate.id == "GATE_SETUP_SLACK"
        )
        assert setup.timing_slack.ws_ns == 16.622
        assert setup.timing_slack.wns_ns == 0.0
        assert setup.timing_slack.nvp == 0

    def test_running_stage_is_not_verified(self):
        states = dict(ALL_SUCCESS)
        states["sta"] = "Ongoing"
        assert _status(make_inputs(gcd_metrics(), states)) == "NOT_VERIFIED"


def _gate(inputs, gate_id):
    return next(gate for gate in evaluate_feasibility(inputs).gates if gate.id == gate_id)


def _corners(**overrides):
    base = {"setup_ws": 16.622, "hold_ws": 0.1, "setup_nvp": 0, "hold_nvp": 0}
    return [
        CornerSlack("MAX/Cworst", **{**base, **overrides}),
        CornerSlack("MIN/Cbest", **{**base, "setup_ws": 18.98}),
    ]


class TestPerCornerGates:
    def test_consistent_corners_pass_with_unchanged_slack_view(self):
        inputs = make_inputs(gcd_metrics(), ALL_SUCCESS, corners=_corners())
        feasibility = evaluate_feasibility(inputs)
        assert feasibility.status == "PASS"
        setup = next(g for g in feasibility.gates if g.id == "GATE_SETUP_SLACK")
        assert setup.timing_slack.ws_ns == 16.622

    def test_failing_corner_fails_even_if_aggregate_passes(self):
        inputs = make_inputs(
            gcd_metrics(), ALL_SUCCESS, corners=_corners(setup_ws=-0.5, setup_nvp=3)
        )
        feasibility = evaluate_feasibility(inputs)
        assert feasibility.status == "PHYSICAL_FAIL"
        setup = next(g for g in feasibility.gates if g.id == "GATE_SETUP_SLACK")
        assert setup.state == "failed"
        assert setup.timing_slack.ws_ns == -0.5

    def test_failing_hold_corner_fails_even_if_aggregate_passes(self):
        inputs = make_inputs(gcd_metrics(), ALL_SUCCESS, corners=_corners(hold_ws=-0.02))
        assert _gate(inputs, "GATE_HOLD_SLACK").state == "failed"

    def test_missing_corner_is_unknown_with_reason(self):
        inputs = make_inputs(gcd_metrics(), ALL_SUCCESS, corners=_corners()[:1])
        gate = _gate(inputs, "GATE_SETUP_SLACK")
        assert (gate.state, gate.availability) == ("unavailable", "corrupt")
        assert "1 of 2 expected corners" in gate.reason
        assert _status(inputs) == "UNKNOWN"

    def test_missing_corner_does_not_hide_a_failing_corner(self):
        inputs = make_inputs(gcd_metrics(), ALL_SUCCESS, corners=_corners(setup_ws=-0.5)[:1])
        assert _status(inputs) == "PHYSICAL_FAIL"

    def test_aggregate_disagreement_is_unknown(self):
        metrics = gcd_metrics()
        metrics["sta_setup_wns"].value = 20.0  # worst corner says 16.622
        inputs = make_inputs(metrics, ALL_SUCCESS, corners=_corners())
        gate = _gate(inputs, "GATE_SETUP_SLACK")
        assert gate.availability == "corrupt"
        assert "disagrees" in gate.reason

    def test_rounding_tolerance_is_accepted(self):
        metrics = gcd_metrics()
        metrics["sta_setup_wns"].value = 16.6225
        inputs = make_inputs(metrics, ALL_SUCCESS, corners=_corners())
        assert _status(inputs) == "PASS"

    def test_violation_count_disagreement_is_unknown(self):
        inputs = make_inputs(gcd_metrics(), ALL_SUCCESS, corners=_corners(setup_nvp=2))
        gate = _gate(inputs, "GATE_SETUP_SLACK")
        assert gate.availability == "corrupt"
        assert "sta_setup_violation_count" in gate.reason

    def test_no_corner_data_falls_back_to_aggregate(self):
        assert _status(make_inputs(gcd_metrics(), ALL_SUCCESS, corners=[])) == "PASS"

    def test_unparseable_corner_summaries_make_gate_corrupt(self):
        inputs = make_inputs(gcd_metrics(), ALL_SUCCESS, corners=[], sta_corner_parse_failures=2)
        gate = _gate(inputs, "GATE_SETUP_SLACK")
        assert gate.availability == "corrupt"
        assert "no valid per-corner" in gate.reason
        assert _status(inputs) == "UNKNOWN"

    def test_failing_corner_with_aggregate_disagreement_preserves_reason(self):
        metrics = gcd_metrics()
        metrics["sta_setup_wns"].value = 20.0
        inputs = make_inputs(metrics, ALL_SUCCESS, corners=_corners(setup_ws=-0.5, setup_nvp=3))
        gate = _gate(inputs, "GATE_SETUP_SLACK")
        assert gate.state == "failed"
        assert gate.reason is not None
        assert "disagrees" in gate.reason
        assert evaluate_feasibility(inputs).status == "PHYSICAL_FAIL"
