"""The seven authoritative physical signoff gates (spec §10).

Gate evaluation distinguishes a physical failure from missing evidence:
a missing report or corner never becomes PHYSICAL_FAIL. Reduction order
is strict: any failed gate vetoes everything; corrupt evidence yields
UNKNOWN; omitted verification yields NOT_VERIFIED; only all-pass (or
waived) yields PASS.
"""

from chipcompiler.analysis.qor.gate_catalog import WORKSPACE_GATES, WorkspaceGateSpec
from chipcompiler.analysis.qor.metric_registry import clamped_wns
from chipcompiler.analysis.qor.models import Feasibility, FeasibilityGate, SlackView
from chipcompiler.data import StateEnum

_PHYSICAL_FAIL = "PHYSICAL_FAIL"
_UNKNOWN = "UNKNOWN"
_NOT_VERIFIED = "NOT_VERIFIED"
_PASS = "PASS"


def _slack_gate(spec: WorkspaceGateSpec, inputs) -> FeasibilityGate:
    state = inputs.step_state(spec.step)
    ws = inputs.value(spec.metric_id)
    worst_corner_record = (
        inputs.metrics.get("sta_worst_setup_corner")
        if spec.metric_id.startswith("sta_setup")
        else None
    )
    if state != StateEnum.Success.value:
        return FeasibilityGate(
            id=spec.id,
            stage=spec.stage,
            state="unavailable",
            predicate=f"{spec.metric_id} >= 0.0",
            blocks_tapeout=True,
            metrics=[spec.metric_id],
            availability="not_verified",
        )
    if ws is None:
        return FeasibilityGate(
            id=spec.id,
            stage=spec.stage,
            state="unavailable",
            predicate=f"{spec.metric_id} >= 0.0",
            blocks_tapeout=True,
            metrics=[spec.metric_id],
            availability="corrupt",
        )
    tns = inputs.value(spec.tns_metric) if spec.tns_metric else None
    nvp_value = inputs.value(spec.nvp_metric) if spec.nvp_metric else None
    slack = SlackView(
        ws_ns=ws,
        wns_ns=clamped_wns(ws),
        tns_ns=tns,
        nvp=int(nvp_value) if nvp_value is not None else None,
        worst_corner=worst_corner_record.value if worst_corner_record is not None else None,
    )
    return FeasibilityGate(
        id=spec.id,
        stage=spec.stage,
        state="passed" if ws >= 0.0 else "failed",
        predicate=f"{spec.metric_id} >= 0.0",
        blocks_tapeout=True,
        metrics=[spec.metric_id],
        timing_slack=slack,
    )


def _count_gate(spec: WorkspaceGateSpec, inputs) -> FeasibilityGate:
    state = inputs.step_state(spec.step)
    if state != StateEnum.Success.value:
        return FeasibilityGate(
            id=spec.id,
            stage=spec.stage,
            state="unavailable",
            predicate=f"{spec.metric_id} == 0",
            blocks_tapeout=True,
            metrics=[spec.metric_id],
            availability="not_verified",
        )
    value = inputs.value(spec.metric_id)
    if value is None:
        return FeasibilityGate(
            id=spec.id,
            stage=spec.stage,
            state="unavailable",
            predicate=f"{spec.metric_id} == 0",
            blocks_tapeout=True,
            metrics=[spec.metric_id],
            availability="corrupt",
        )
    return FeasibilityGate(
        id=spec.id,
        stage=spec.stage,
        state="passed" if value == 0 else "failed",
        predicate=f"{spec.metric_id} == 0",
        blocks_tapeout=True,
        metrics=[spec.metric_id],
    )


def evaluate_feasibility(inputs) -> Feasibility:
    gates = [
        _slack_gate(spec, inputs) if spec.tns_metric else _count_gate(spec, inputs)
        for spec in WORKSPACE_GATES
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
