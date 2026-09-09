from chipcompiler.analysis.qor.feasibility import evaluate_feasibility
from test.analysis.qor.helpers import gcd_metrics, make_inputs

ALL_SUCCESS = {
    step: "Success"
    for step in (
        "Synthesis",
        "Floorplan",
        "place",
        "CTS",
        "route",
        "drc",
        "lvs",
        "RCX",
        "sta",
        "Harden",
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
