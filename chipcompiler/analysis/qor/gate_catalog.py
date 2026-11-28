"""Stable QoR gate identifiers shared by checklist and workspace analysis."""

from dataclasses import dataclass

from chipcompiler.data import StepEnum

# Step-level gates emitted by tools/ecc/metrics.py into analysis/qor_summary.json.
QOR_STEP_GATE_IDS = {
    StepEnum.DRC.value: ("qor.drc.clean",),
    StepEnum.LVS.value: ("qor.lvs.clean",),
    StepEnum.ANTENNA_CHECK.value: ("qor.antenna.clean",),
    StepEnum.RCX.value: (
        "qor.rcx.corner_coverage",
        "qor.rcx.spef_parse_health",
    ),
    StepEnum.STA.value: (
        "qor.sta.setup_closed",
        "qor.sta.hold_closed",
        "qor.sta.drv_clean",
    ),
    StepEnum.HARDEN.value: (
        "qor.mpc.minimum_area",
        "qor.mpc.maximum_area",
    ),
}


# Step gates that always emit advisory warnings rather than blocking tapeout export
# (e.g. STA DRV closure until #230 physical DRV repair is wired into flows).
STEP_GATE_WARN_ALWAYS = frozenset({"qor.sta.drv_clean"})
# Step gates that warn while their evidence is unavailable (but still block on
# failure): a PDK without antenna rules analyses 0 nets/pins, which is unverified.
STEP_GATE_WARN_WHEN_UNAVAILABLE = frozenset({"qor.antenna.clean"})


def step_gate_blocking(gate_id: str) -> bool:
    """Return whether failing ``gate_id`` blocks tapeout export."""
    return gate_id not in STEP_GATE_WARN_ALWAYS


def step_gate_policy(gate_id: str, state: str, *, blocking: bool | None = None) -> str:
    """Return the checklist policy (``warn`` or ``block``) for a step QoR gate."""
    resolved_blocking = step_gate_blocking(gate_id) if blocking is None else blocking
    if (
        not resolved_blocking
        or gate_id in STEP_GATE_WARN_ALWAYS
        or (gate_id in STEP_GATE_WARN_WHEN_UNAVAILABLE and state == "unavailable")
    ):
        return "warn"
    return "block"


@dataclass(frozen=True)
class WorkspaceGateSpec:
    """One authoritative workspace feasibility gate."""

    id: str
    stage: str
    step: str
    metric_id: str
    qor_gate_ids: tuple[str, ...] = ()
    tns_metric: str | None = None
    nvp_metric: str | None = None
    # Metrics that must all be > 0 for a zero count to mean verified (vacuous-check guard).
    coverage_metrics: tuple[str, ...] = ()
    # Evaluated only when the flow contains this step (older flows lack it).
    only_if_in_flow: bool = False
    # True when failure or missing evidence blocks workspace feasibility/export.
    blocks_tapeout: bool = True


# Workspace feasibility may split an aggregate step gate into scoring aspects.
# This tuple is the only definition of gate order and evaluation inputs.
WORKSPACE_GATES = (
    WorkspaceGateSpec(
        "GATE_DRC",
        "DRC",
        "drc",
        "drc_count",
        ("qor.drc.clean",),
    ),
    WorkspaceGateSpec(
        "GATE_LVS",
        "LVS",
        "lvs",
        "lvs_count",
        ("qor.lvs.clean",),
    ),
    WorkspaceGateSpec(
        "GATE_ANTENNA",
        "ANTENNA",
        StepEnum.ANTENNA_CHECK.value,
        "antenna_violation_count",
        ("qor.antenna.clean",),
        coverage_metrics=("antenna_signal_net_count", "antenna_gate_pin_count"),
        only_if_in_flow=True,
    ),
    WorkspaceGateSpec(
        "GATE_SETUP_SLACK",
        "STA",
        "sta",
        "sta_setup_wns",
        ("qor.sta.setup_closed",),
        tns_metric="sta_setup_tns",
        nvp_metric="sta_setup_violation_count",
    ),
    WorkspaceGateSpec(
        "GATE_HOLD_SLACK",
        "STA",
        "sta",
        "sta_hold_wns",
        ("qor.sta.hold_closed",),
        tns_metric="sta_hold_tns",
        nvp_metric="sta_hold_violation_count",
    ),
    WorkspaceGateSpec(
        "GATE_SETUP_NVP",
        "STA",
        "sta",
        "sta_setup_violation_count",
        ("qor.sta.setup_closed",),
    ),
    WorkspaceGateSpec(
        "GATE_HOLD_NVP",
        "STA",
        "sta",
        "sta_hold_violation_count",
        ("qor.sta.hold_closed",),
    ),
    WorkspaceGateSpec(
        "GATE_MAX_TRANSITION",
        "STA",
        "sta",
        "sta_max_transition_violation_count",
        ("qor.sta.drv_clean",),
        blocks_tapeout=False,
    ),
    WorkspaceGateSpec(
        "GATE_MAX_CAPACITANCE",
        "STA",
        "sta",
        "sta_max_capacitance_violation_count",
        ("qor.sta.drv_clean",),
        blocks_tapeout=False,
    ),
    WorkspaceGateSpec(
        "GATE_MAX_FANOUT",
        "STA",
        "sta",
        "sta_max_fanout_violation_count",
        ("qor.sta.drv_clean",),
        blocks_tapeout=False,
    ),
    WorkspaceGateSpec(
        "GATE_HARDEN_ARTIFACTS",
        "HARDEN",
        "harden",
        "harden_artifact_missing_count",
        ("qor.mpc.maximum_area",),
    ),
)

_QOR_GATE_IDS = tuple(
    dict.fromkeys(gate_id for ids in QOR_STEP_GATE_IDS.values() for gate_id in ids)
)
WORKSPACE_GATE_ALIASES = {
    gate_id: tuple(spec.id for spec in WORKSPACE_GATES if gate_id in spec.qor_gate_ids)
    for gate_id in _QOR_GATE_IDS
}


def gate_metric_ids() -> frozenset[str]:
    """Metric ids that feed a workspace gate (value, TNS, violation and coverage counts)."""
    return frozenset(
        metric_id
        for spec in WORKSPACE_GATES
        for metric_id in (spec.metric_id, spec.tns_metric, spec.nvp_metric, *spec.coverage_metrics)
        if metric_id
    )
