import pytest

from chipcompiler.analysis.qor.feasibility import evaluate_feasibility
from test.analysis.qor.helpers import gcd_metrics, make_inputs, make_metric

SUCCESS = "Success"


def _antenna_gate(violations=None, nets=None, pins=None, state=SUCCESS, *, in_flow=True):
    metrics = gcd_metrics()
    if violations is not None:
        metrics["antenna_violation_count"] = make_metric(
            "antenna_violation_count", violations, step="antenna_check"
        )
    if nets is not None:
        metrics["antenna_signal_net_count"] = make_metric(
            "antenna_signal_net_count", nets, step="antenna_check"
        )
    if pins is not None:
        metrics["antenna_gate_pin_count"] = make_metric(
            "antenna_gate_pin_count", pins, step="antenna_check"
        )
    inputs = make_inputs(metrics, tclk_ns=20.0)
    if in_flow:
        inputs.flow_states["antenna_check"] = state
    feasibility = evaluate_feasibility(inputs)
    gate = next((g for g in feasibility.gates if g.id == "GATE_ANTENNA"), None)
    return feasibility, gate


def test_gate_is_skipped_for_flows_without_antenna_step():
    feasibility, gate = _antenna_gate(in_flow=False)
    assert gate is None
    assert feasibility.status == "PASS"


def test_analysed_clean_antenna_check_passes():
    feasibility, gate = _antenna_gate(violations=0, nets=4213, pins=9781)
    assert gate is not None
    assert gate.state == "passed"
    assert feasibility.status == "PASS"


@pytest.mark.parametrize("violations", [1, 37])
def test_antenna_violations_are_a_physical_fail(violations):
    feasibility, gate = _antenna_gate(violations=violations, nets=4213, pins=9781)
    assert gate is not None
    assert gate.state == "failed"
    assert gate.blocks_tapeout is True
    assert feasibility.status == "PHYSICAL_FAIL"


def test_antenna_violations_fail_even_with_zero_coverage():
    feasibility, gate = _antenna_gate(violations=3, nets=0, pins=0)
    assert gate is not None
    assert gate.state == "failed"
    assert feasibility.status == "PHYSICAL_FAIL"


@pytest.mark.parametrize(("nets", "pins"), [(0, 9781), (4213, 0), (0, 0)])
def test_vacuous_antenna_check_is_not_verified_not_pass(nets, pins):
    feasibility, gate = _antenna_gate(violations=0, nets=nets, pins=pins)
    assert gate is not None
    assert gate.state == "unavailable"
    assert gate.availability == "not_verified"
    assert feasibility.status == "NOT_VERIFIED"


def test_missing_gate_pin_count_is_corrupt_evidence():
    feasibility, gate = _antenna_gate(violations=0, nets=4213, pins=None)
    assert gate is not None
    assert gate.state == "unavailable"
    assert gate.availability == "corrupt"
    assert feasibility.status == "UNKNOWN"


def test_failed_antenna_step_is_not_verified():
    feasibility, gate = _antenna_gate(violations=0, nets=10, pins=20, state="Incomplete")
    assert gate is not None
    assert gate.availability == "not_verified"
    assert feasibility.status == "NOT_VERIFIED"


def test_missing_violation_metric_is_corrupt_evidence():
    feasibility, gate = _antenna_gate(nets=10, pins=20)
    assert gate is not None
    assert gate.availability == "corrupt"
    assert feasibility.status == "UNKNOWN"
