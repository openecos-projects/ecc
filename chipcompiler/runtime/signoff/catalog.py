"""Signoff checklist item catalog — identity / policy / readiness impact.

Builders fill state/summary/evidence; this module owns the slot table.
Dynamic ``package.*`` rows are the only unbounded family (collector issues).

In:
    (none — static table + lookup helpers)
Out:
    SIGNOFF_ITEM_CATALOG — frozen SignoffItemSpec rows
    lookup_item / required_item_ids / catalog_defaults — query helpers
Entry:
    build_checklist()           chipcompiler/tools/ecc/signoff_checklist.py
    build_signoff_assessment()  chipcompiler/engine/signoff_assessment.py
See:
    classify_signoff_readiness() chipcompiler/runtime/signoff/readiness.py
    generate-signoff-kanban.py   nix/scripts/generate-signoff-kanban.py
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


def _flow(step: str, *, optional: bool | None = None) -> SignoffItemSpec:
    if optional is None:
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


def _quality_optional(gate_id: str, step: str, title: str) -> SignoffItemSpec:
    """Quality-shaped slot not yet bound to a blocking QoR gate."""
    return SignoffItemSpec(
        id=f"quality.{gate_id.removeprefix('qor.')}",
        step=step,
        category="quality_gate",
        owner="qor",
        policy="warn",
        title=title,
        qor_gate=gate_id,
        optional=True,
        fail_readiness="WARN",
    )


def _performance(item_id: str, step: str, title: str) -> SignoffItemSpec:
    """Numeric PPA / iSTA catalog slots (unbound placeholders; not checklist-wired)."""
    return SignoffItemSpec(
        id=item_id,
        step=step,
        category="performance",
        owner="qor",
        policy="warn",
        title=title,
        optional=True,
        fail_readiness="WARN",
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
        "artifact.sdc.constraints",
        "workspace",
        "SDC constraints file",
        optional=True,
    ),
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
    # Early / mid-chain flow (optional until checklist builders bind evidence).
    _flow(StepEnum.SYNTHESIS.value, optional=True),
    _flow(StepEnum.PLACEMENT.value, optional=True),
    _flow(StepEnum.CTS.value, optional=True),
    _flow(StepEnum.LEGALIZATION.value, optional=True),
    _flow(StepEnum.POWER_ANALYSIS.value, optional=True),
    # Soft quality (optional) — CTS skew target / route DR.
    _quality_optional("qor.cts.skew_target", StepEnum.CTS.value, "CTS skew target met"),
    _quality_optional("qor.route.dr_clean", StepEnum.ROUTING.value, "Route DR clean"),
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
    # Performance placeholders (not checklist-wired). Numbers: runtime.signoff.qor_perf_support.
    # Reading on the board = "<value> <unit>".
    _performance("performance.sta.setup_wns", StepEnum.STA.value, "STA setup WNS"),
    _performance("performance.sta.setup_tns", StepEnum.STA.value, "STA setup TNS"),
    _performance("performance.sta.hold_wns", StepEnum.STA.value, "STA hold WNS"),
    _performance("performance.sta.hold_tns", StepEnum.STA.value, "STA hold TNS"),
    _performance("performance.sta.frequency", StepEnum.STA.value, "STA frequency"),
    _performance("performance.power.dynamic", StepEnum.STA.value, "Dynamic power"),
    _performance("performance.power.leakage", StepEnum.STA.value, "Leakage power"),
    _performance("performance.sdc.clock_count", "workspace", "SDC clock count"),
    _performance("performance.cts.skew", StepEnum.CTS.value, "CTS worst skew"),
    _performance(
        "performance.cts.insertion_latency",
        StepEnum.CTS.value,
        "CTS max insertion latency",
    ),
    _performance("performance.cts.buffer_count", StepEnum.CTS.value, "CTS buffer count"),
    _performance("performance.cts.clock_wirelength", StepEnum.CTS.value, "CTS clock wirelength"),
    _performance("performance.cts.tree_max_level", StepEnum.CTS.value, "CTS clock tree max level"),
    _performance("performance.place.hpwl", StepEnum.PLACEMENT.value, "Place HPWL"),
    _performance(
        "performance.place.congestion_overflow",
        StepEnum.PLACEMENT.value,
        "Place EGR overflow total",
    ),
    _performance("performance.route.wirelength", StepEnum.ROUTING.value, "Route wirelength"),
    _performance("performance.route.via_count", StepEnum.ROUTING.value, "Route via count"),
    _performance(
        "performance.synthesis.cell_area", StepEnum.SYNTHESIS.value, "Synthesis cell area"
    ),
    _performance(
        "performance.synthesis.cell_count", StepEnum.SYNTHESIS.value, "Synthesis cell count"
    ),
    _performance("performance.host.latency", "host", "组件耗时"),
    _performance("performance.host.throughput", "host", "速度"),
    _performance("performance.host.peak_memory", "host", "内存峰值"),
    _performance("performance.host.avg_memory", "host", "内存平均"),
    _performance("performance.host.compile_peak_memory", "host", "编译内存峰值"),
)

CATALOG_BY_ID: dict[str, SignoffItemSpec] = {item.id: item for item in SIGNOFF_ITEM_CATALOG}

PACKAGE_ID_PREFIX = "package."


def lookup_item(item_id: str) -> SignoffItemSpec | None:
    """Resolve one catalog slot (incl. dynamic ``package.*``).

    In:
        item_id — checklist item id
    Out:
        SignoffItemSpec | None — catalog row, or None if unknown
    See:
        required_item_ids()         chipcompiler/runtime/signoff/catalog.py
        build_checklist()           chipcompiler/tools/ecc/signoff_checklist.py
    """
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
    """Ids that must appear for a full blocking package.

    In:
        include_post_route_lec — when True, keep optional postRouteLec slots
    Out:
        tuple[str, ...] — ordered required item ids
    See:
        lookup_item()               chipcompiler/runtime/signoff/catalog.py
        SIGNOFF_ITEM_CATALOG        chipcompiler/runtime/signoff/catalog.py
    """
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
    """Default step/category/owner/policy/title for a known id.

    In:
        item_id — catalog id
    Out:
        dict — empty if unknown; else step/category/owner/policy/title
    See:
        lookup_item()  chipcompiler/runtime/signoff/catalog.py
    """
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
