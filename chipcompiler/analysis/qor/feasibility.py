"""The seven authoritative physical signoff gates (spec §10).

Gate evaluation distinguishes a physical failure from missing evidence:
a missing report or corner never becomes PHYSICAL_FAIL. Reduction order
is strict: any failed gate vetoes everything; corrupt evidence yields
UNKNOWN; omitted verification yields NOT_VERIFIED; only all-pass (or
waived) yields PASS.
"""

from chipcompiler.analysis.qor.metric_registry import clamped_wns
from chipcompiler.analysis.qor.models import Feasibility, FeasibilityGate, SlackView
from chipcompiler.data import StateEnum

_PHYSICAL_FAIL = "PHYSICAL_FAIL"
_UNKNOWN = "UNKNOWN"
_NOT_VERIFIED = "NOT_VERIFIED"
_PASS = "PASS"


def _slack_gate(gate_id, stage, step_value, ws_metric, tns_metric, nvp_metric, inputs):
    state = inputs.step_state(step_value)
    ws = inputs.value(ws_metric)
    worst_corner_record = (
        inputs.metrics.get("sta_worst_setup_corner") if ws_metric.startswith("sta_setup") else None
    )
    if state != StateEnum.Success.value:
        return FeasibilityGate(
            id=gate_id,
            stage=stage,
            state="unavailable",
            predicate=f"{ws_metric} >= 0.0",
            blocks_tapeout=True,
            metrics=[ws_metric],
            availability="not_verified",
        )
    if ws is None:
        return FeasibilityGate(
            id=gate_id,
            stage=stage,
            state="unavailable",
            predicate=f"{ws_metric} >= 0.0",
            blocks_tapeout=True,
            metrics=[ws_metric],
            availability="corrupt",
        )
    slack = SlackView(
        ws_ns=ws,
        wns_ns=clamped_wns(ws),
        tns_ns=inputs.value(tns_metric),
        nvp=int(inputs.value(nvp_metric)) if inputs.value(nvp_metric) is not None else None,
        worst_corner=worst_corner_record.value if worst_corner_record is not None else None,
    )
    return FeasibilityGate(
        id=gate_id,
        stage=stage,
        state="passed" if ws >= 0.0 else "failed",
        predicate=f"{ws_metric} >= 0.0",
        blocks_tapeout=True,
        metrics=[ws_metric],
        timing_slack=slack,
    )


def _count_gate(gate_id, stage, step_value, metric_id, inputs):
    state = inputs.step_state(step_value)
    if state != StateEnum.Success.value:
        return FeasibilityGate(
            id=gate_id,
            stage=stage,
            state="unavailable",
            predicate=f"{metric_id} == 0",
            blocks_tapeout=True,
            metrics=[metric_id],
            availability="not_verified",
        )
    value = inputs.value(metric_id)
    if value is None:
        return FeasibilityGate(
            id=gate_id,
            stage=stage,
            state="unavailable",
            predicate=f"{metric_id} == 0",
            blocks_tapeout=True,
            metrics=[metric_id],
            availability="corrupt",
        )
    return FeasibilityGate(
        id=gate_id,
        stage=stage,
        state="passed" if value == 0 else "failed",
        predicate=f"{metric_id} == 0",
        blocks_tapeout=True,
        metrics=[metric_id],
    )


def evaluate_feasibility(inputs) -> Feasibility:
    gates = [
        _count_gate("GATE_DRC", "DRC", "drc", "drc_count", inputs),
        _count_gate("GATE_LVS", "LVS", "lvs", "lvs_count", inputs),
        _slack_gate(
            "GATE_SETUP_SLACK",
            "STA",
            "sta",
            "sta_setup_wns",
            "sta_setup_tns",
            "sta_setup_violation_count",
            inputs,
        ),
        _slack_gate(
            "GATE_HOLD_SLACK",
            "STA",
            "sta",
            "sta_hold_wns",
            "sta_hold_tns",
            "sta_hold_violation_count",
            inputs,
        ),
        _count_gate("GATE_SETUP_NVP", "STA", "sta", "sta_setup_violation_count", inputs),
        _count_gate("GATE_HOLD_NVP", "STA", "sta", "sta_hold_violation_count", inputs),
        _count_gate(
            "GATE_HARDEN_ARTIFACTS", "HARDEN", "Harden", "harden_artifact_missing_count", inputs
        ),
    ]

    if any(gate.state == "failed" for gate in gates):
        status = _PHYSICAL_FAIL
    elif any(gate.availability == "corrupt" for gate in gates):
        status = _UNKNOWN
    elif any(gate.availability == "not_verified" for gate in gates):
        status = _NOT_VERIFIED
    else:
        status = _PASS
    return Feasibility(status=status, gates=gates)
