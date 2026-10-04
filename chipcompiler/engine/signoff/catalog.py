"""Signoff checklist item catalog — framework substrate for every concrete item.

Builders in ``signoff_checklist`` fill state/summary/evidence; this module owns
identity, policy, owner, and readiness impact. Dynamic ``package.*`` rows are
the only unbounded family (collector issues).
"""

from __future__ import annotations

from dataclasses import dataclass

from chipcompiler.data import SkippableStepEnum, StepEnum

# QoR gate id → checklist item id (strip ``qor.``).
QUALITY_GATES_BY_STEP: dict[str, tuple[str, ...]] = {
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

REQUIRED_FLOW_STEPS: tuple[str, ...] = (
    StepEnum.ROUTING.value,
    StepEnum.DRC.value,
    StepEnum.LVS.value,
    StepEnum.FILLER.value,
    SkippableStepEnum.POST_ROUTE_LEC.value,
    StepEnum.RCX.value,
    StepEnum.STA.value,
    StepEnum.HARDEN.value,
)

CONFIG_FILENAMES: dict[str, str] = {
    "db": "db_ecc.json",
    StepEnum.RCX.value: "rcx_ecc.json",
    StepEnum.STA.value: "sta_ecc.json",
}


@dataclass(frozen=True)
class SignoffItemSpec:
    """One checklist slot. ``optional`` means the item may be absent (skipped LEC)."""

    id: str
    step: str
    category: str
    owner: str
    policy: str
    title: str
    optional: bool = False
    qor_gate: str | None = None
    # When blocked+failed: QoR → ERROR, missing evidence → MISS.
    fail_readiness: str = "MISS"


def _quality(gate_id: str, step: str, title: str) -> SignoffItemSpec:
    return SignoffItemSpec(
        id=f"quality.{gate_id.removeprefix('qor.')}",
        step=step,
        category="quality_gate",
        owner="qor",
        policy="block",
        title=title,
        qor_gate=gate_id,
        fail_readiness="ERROR",
    )


def _artifact(
    item_id: str, step: str, title: str, *, category: str = "artifact", optional: bool = False
) -> SignoffItemSpec:
    return SignoffItemSpec(
        id=item_id,
        step=step,
        category=category,
        owner="checklist",
        policy="block",
        title=title,
        optional=optional,
        fail_readiness="MISS",
    )


def _flow(step: str) -> SignoffItemSpec:
    optional = step == SkippableStepEnum.POST_ROUTE_LEC.value
    return SignoffItemSpec(
        id=f"flow.{step.lower()}.completed",
        step=step,
        category="flow",
        owner="checklist",
        policy="block",
        title=f"{step} flow completed",
        optional=optional,
        fail_readiness="MISS",
    )


SIGNOFF_ITEM_CATALOG: tuple[SignoffItemSpec, ...] = (
    # Quality gates (QoR owns the predicate).
    _quality("qor.drc.clean", StepEnum.DRC.value, "Final DRC clean"),
    _quality("qor.lvs.clean", StepEnum.LVS.value, "Final LVS clean"),
    _quality("qor.rcx.corner_coverage", StepEnum.RCX.value, "RCX corner coverage"),
    _quality("qor.rcx.spef_parse_health", StepEnum.RCX.value, "RCX SPEF integrity"),
    _quality("qor.sta.setup_closed", StepEnum.STA.value, "STA setup closure"),
    _quality("qor.sta.hold_closed", StepEnum.STA.value, "STA hold closure"),
    _quality("qor.mpc.minimum_area", StepEnum.HARDEN.value, "Minimum core area"),
    _quality("qor.mpc.maximum_area", StepEnum.HARDEN.value, "Maximum core area"),
    # Step artifacts / reports.
    _artifact("artifact.harden.gds", StepEnum.HARDEN.value, "Harden GDS"),
    _artifact("artifact.harden.lef", StepEnum.HARDEN.value, "Harden LEF"),
    _artifact("artifact.harden.lib", StepEnum.HARDEN.value, "Harden LIB"),
    _artifact("artifact.lvs.def", StepEnum.LVS.value, "LVS DEF"),
    _artifact("artifact.lvs.verilog", StepEnum.LVS.value, "LVS Verilog"),
    _artifact("artifact.lvs.gds", StepEnum.LVS.value, "LVS GDS"),
    _artifact("artifact.lvs.report", StepEnum.LVS.value, "LVS report", category="report"),
    _artifact("artifact.lvs.json", StepEnum.LVS.value, "LVS JSON"),
    _artifact("artifact.rcx.spef_outputs", StepEnum.RCX.value, "RCX SPEF outputs"),
    _artifact(
        "report.sta.timing_reports",
        StepEnum.STA.value,
        "STA timing reports",
        category="report",
    ),
    _artifact(
        "artifact.sta.corner_summaries",
        StepEnum.STA.value,
        "STA structured corner summaries",
    ),
    _artifact("artifact.sta.timing_paths", StepEnum.STA.value, "STA structured timing paths"),
    _artifact("artifact.synthesis.netlist", StepEnum.SYNTHESIS.value, "Mapped synthesis netlist"),
    _artifact(
        "artifact.postroutelec.result",
        SkippableStepEnum.POST_ROUTE_LEC.value,
        "Post-route LEC result",
        optional=True,
    ),
    _artifact(
        "artifact.lec.result",
        SkippableStepEnum.LEC.value,
        "Synthesis LEC result",
        optional=True,
    ),
    # Required flow completion (postRouteLec omitted when the ledger skipped it).
    *(_flow(step) for step in REQUIRED_FLOW_STEPS),
    # Workspace provenance + config snapshots.
    SignoffItemSpec(
        id="provenance.initial.rtl",
        step="workspace",
        category="provenance",
        owner="checklist",
        policy="block",
        title="Initial RTL",
        fail_readiness="MISS",
    ),
    SignoffItemSpec(
        id="provenance.initial.sdc",
        step="workspace",
        category="provenance",
        owner="checklist",
        policy="block",
        title="Initial SDC",
        fail_readiness="MISS",
    ),
    SignoffItemSpec(
        id="configuration.db",
        step="workspace",
        category="configuration",
        owner="checklist",
        policy="block",
        title="Configuration db",
        fail_readiness="MISS",
    ),
    SignoffItemSpec(
        id="configuration.rcx",
        step="workspace",
        category="configuration",
        owner="checklist",
        policy="block",
        title="Configuration RCX",
        fail_readiness="MISS",
    ),
    SignoffItemSpec(
        id="configuration.sta",
        step="workspace",
        category="configuration",
        owner="checklist",
        policy="block",
        title="Configuration sta",
        fail_readiness="MISS",
    ),
)

CATALOG_BY_ID: dict[str, SignoffItemSpec] = {item.id: item for item in SIGNOFF_ITEM_CATALOG}

PACKAGE_ID_PREFIX = "package."


def lookup_item(item_id: str) -> SignoffItemSpec | None:
    spec = CATALOG_BY_ID.get(item_id)
    if spec is not None:
        return spec
    if item_id.startswith(PACKAGE_ID_PREFIX) and item_id != PACKAGE_ID_PREFIX:
        return SignoffItemSpec(
            id=item_id,
            step="workspace",
            category="artifact",
            owner="checklist",
            policy="warn",
            title="Signoff package resource",
            optional=True,
            fail_readiness="MISS",
        )
    return None


def required_item_ids(*, include_post_route_lec: bool = True) -> tuple[str, ...]:
    ids = []
    lec_when_required = {
        "artifact.postroutelec.result",
        "flow.postroutelec.completed",
    }
    for item in SIGNOFF_ITEM_CATALOG:
        if item.id == "artifact.lec.result":
            continue
        if item.optional:
            if include_post_route_lec and item.id in lec_when_required:
                ids.append(item.id)
            continue
        ids.append(item.id)
    return tuple(ids)


def catalog_defaults(item_id: str) -> dict[str, str]:
    spec = CATALOG_BY_ID.get(item_id)
    if spec is None:
        return {}
    return {
        "step": spec.step,
        "category": spec.category,
        "owner": spec.owner,
        "policy": spec.policy,
        "title": spec.title,
    }
