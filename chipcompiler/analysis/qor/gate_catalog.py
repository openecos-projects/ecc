"""Stable QoR gate identifiers shared by checklist and workspace analysis."""

from dataclasses import dataclass

from chipcompiler.data import StepEnum

# Step-level gates emitted by tools/ecc/metrics.py into analysis/qor_summary.json.
QOR_STEP_GATE_IDS = {
    StepEnum.DRC.value: ("qor.drc.clean",),
    StepEnum.LVS.value: ("qor.lvs.clean",),
    StepEnum.RCX.value: (
        "qor.rcx.corner_coverage",
        "qor.rcx.spef_parse_health",
    ),
    StepEnum.STA.value: (
        "qor.sta.setup_closed",
        "qor.sta.hold_closed",
    ),
    StepEnum.HARDEN.value: (
        "qor.mpc.minimum_area",
        "qor.mpc.maximum_area",
    ),
}


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
        "GATE_HARDEN_ARTIFACTS",
        "HARDEN",
        "Harden",
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
