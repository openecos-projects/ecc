"""The authoritative physical signoff gates (spec §10), including the STA DRV gates.

Gate evaluation distinguishes a physical failure from missing evidence:
a missing report or corner never becomes PHYSICAL_FAIL. Reduction is
decided by blocking gates (``blocks_tapeout=True``): any failed blocking
gate vetoes everything; corrupt blocking evidence yields UNKNOWN; omitted
blocking verification yields NOT_VERIFIED; advisory gates
(``blocks_tapeout=False``) surface findings in ``Feasibility.gates``
without triggering PHYSICAL_FAIL or vetoing the composite score.
"""

from chipcompiler.analysis.qor.gate_catalog import WORKSPACE_GATES, WorkspaceGateSpec
from chipcompiler.analysis.qor.metric_registry import clamped_wns
from chipcompiler.analysis.qor.models import Feasibility, FeasibilityGate, SlackView
from chipcompiler.data import StateEnum

_PHYSICAL_FAIL = "PHYSICAL_FAIL"
_UNKNOWN = "UNKNOWN"
_NOT_VERIFIED = "NOT_VERIFIED"
_PASS = "PASS"

# Aggregate STA slacks are written rounded to 3 decimals; allow that much.
_AGGREGATE_WS_TOLERANCE_NS = 1.5e-3


def corner_slack_check(inputs, metric_id: str, nvp_metric: str | None, ws: float):
    """Cross-check an aggregate STA slack against the per-corner summaries.

    Returns ``(corner_ws, reason)``. ``corner_ws`` is the worst per-corner
    slack, or None when no per-corner data exists (the aggregate alone then
    decides). ``reason`` is set when the
    per-corner evidence is incomplete or disagrees with the aggregate.
    """
    is_setup = metric_id.startswith("sta_setup")
    kind = "setup" if is_setup else "hold"
    loaded = [
        (corner.setup_ws if is_setup else corner.hold_ws, corner.corner)
        for corner in inputs.corners
        if (corner.setup_ws if is_setup else corner.hold_ws) is not None
    ]
    expected = inputs.sta_expected_corners
    if not loaded:
        if getattr(inputs, "sta_corner_parse_failures", 0) > 0:
            return None, f"no valid per-corner {kind} summary could be parsed"
        # No per-corner evidence at all (legacy or aggregate-only workspace):
        # the aggregate alone decides, as before.
        return None, None
    corner_ws, corner = min(loaded)
    reason = None
    if expected is not None and len(loaded) < expected:
        reason = (
            f"only {len(loaded)} of {int(expected)} expected corners have a valid {kind} summary"
        )
    elif abs(corner_ws - ws) > _AGGREGATE_WS_TOLERANCE_NS:
        reason = (
            f"aggregate {metric_id}={ws:g} disagrees with worst per-corner {kind} "
            f"slack {corner_ws:g} ({corner})"
        )
    elif nvp_metric:
        nvp = inputs.value(nvp_metric)
        if nvp is not None:
            counts = [c.setup_nvp if is_setup else c.hold_nvp for c in inputs.corners]
            valid_counts = [count for count in counts if count is not None]
            if len(valid_counts) == len(inputs.corners) and sum(valid_counts) != int(nvp):
                reason = (
                    f"aggregate {nvp_metric}={int(nvp)} disagrees with per-corner "
                    f"total {sum(valid_counts)}"
                )
    return corner_ws, reason


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
            blocks_tapeout=spec.blocks_tapeout,
            metrics=[spec.metric_id],
            availability="not_verified",
        )
    if ws is None:
        return FeasibilityGate(
            id=spec.id,
            stage=spec.stage,
            state="unavailable",
            predicate=f"{spec.metric_id} >= 0.0",
            blocks_tapeout=spec.blocks_tapeout,
            metrics=[spec.metric_id],
            availability="corrupt",
        )
    corner_ws, reason = corner_slack_check(inputs, spec.metric_id, spec.nvp_metric, ws)
    if corner_ws is not None:
        ws = min(ws, corner_ws)  # the worst corner decides
    if ws >= 0.0 and reason is not None:
        return FeasibilityGate(
            id=spec.id,
            stage=spec.stage,
            state="unavailable",
            predicate=f"{spec.metric_id} >= 0.0",
            blocks_tapeout=spec.blocks_tapeout,
            metrics=[spec.metric_id],
            availability="corrupt",
            reason=reason,
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
        blocks_tapeout=spec.blocks_tapeout,
        metrics=[spec.metric_id],
        reason=reason,
        timing_slack=slack,
    )


def _count_gate(spec: WorkspaceGateSpec, inputs) -> FeasibilityGate:
    state = inputs.step_state(spec.step)
    predicate = " and ".join(
        [*(f"{metric_id} > 0" for metric_id in spec.coverage_metrics), f"{spec.metric_id} == 0"]
    )
    gate_metrics = [spec.metric_id, *spec.coverage_metrics]
    if state != StateEnum.Success.value:
        return FeasibilityGate(
            id=spec.id,
            stage=spec.stage,
            state="unavailable",
            predicate=f"{spec.metric_id} == 0",
            blocks_tapeout=spec.blocks_tapeout,
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
            blocks_tapeout=spec.blocks_tapeout,
            metrics=[spec.metric_id],
            availability="corrupt",
        )
    if value != 0:
        return FeasibilityGate(
            id=spec.id,
            stage=spec.stage,
            state="failed",
            predicate=predicate,
            blocks_tapeout=spec.blocks_tapeout,
            metrics=gate_metrics,
        )
    for coverage_metric in spec.coverage_metrics:
        covered = inputs.value(coverage_metric)
        if covered is None:
            return FeasibilityGate(
                id=spec.id,
                stage=spec.stage,
                state="unavailable",
                predicate=predicate,
                blocks_tapeout=spec.blocks_tapeout,
                metrics=gate_metrics,
                availability="corrupt",
            )
        if covered <= 0:
            # The check ran but analysed nothing (no rules / no gate areas):
            # a zero count is not evidence, so the gate cannot pass.
            return FeasibilityGate(
                id=spec.id,
                stage=spec.stage,
                state="unavailable",
                predicate=predicate,
                blocks_tapeout=spec.blocks_tapeout,
                metrics=gate_metrics,
                availability="not_verified",
            )
    return FeasibilityGate(
        id=spec.id,
        stage=spec.stage,
        state="passed",
        predicate=predicate,
        blocks_tapeout=spec.blocks_tapeout,
        metrics=gate_metrics,
    )


def evaluate_feasibility(inputs) -> Feasibility:
    gates = [
        _slack_gate(spec, inputs) if spec.tns_metric else _count_gate(spec, inputs)
        for spec in WORKSPACE_GATES
        if not (spec.only_if_in_flow and inputs.step_state(spec.step) is None)
    ]

    blocking_gates = [gate for gate in gates if gate.blocks_tapeout]
    if any(gate.state == "failed" for gate in blocking_gates):
        status = _PHYSICAL_FAIL
    elif any(gate.availability == "corrupt" for gate in blocking_gates):
        status = _UNKNOWN
    elif any(gate.availability == "not_verified" for gate in blocking_gates):
        status = _NOT_VERIFIED
    else:
        status = _PASS
    return Feasibility(status=status, gates=gates)
