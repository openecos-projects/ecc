#!/usr/bin/env python

from dataclasses import dataclass, field
from pathlib import Path

from chipcompiler.data.types import SkippableStepEnum, StepEnum

# Canonical workspace step-directory names.
#
# Workspace creation names each step directory ``<step>_<tool>`` along the
# canonical rtl2gds chain (``Synthesis_yosys``, ``place_dreamplace``, ...).
# Checklists, signoff packages, QoR scoring, and the design reports all
# resolve per-step artifacts through that naming, so the mapping lives here
# once instead of as hand-maintained tables per consumer. Timing
# optimization is on the canonical chain but owns no artifact directory any
# consumer reads through these tables.
STEP_DIRECTORIES = {
    StepEnum.SYNTHESIS.value: "Synthesis_yosys",
    SkippableStepEnum.LEC.value: "lec_kepler_formal",
    StepEnum.PRE_FLOORPLAN.value: "preFloorplan_ecc",
    StepEnum.MACRO_PLACEMENT.value: "macroPlacement_dreamplace",
    StepEnum.POST_FLOORPLAN.value: "postFloorplan_ecc",
    StepEnum.PLACEMENT.value: "place_dreamplace",
    StepEnum.CTS.value: "CTS_ecc",
    StepEnum.LEGALIZATION.value: "legalization_dreamplace",
    StepEnum.ROUTING.value: "route_ecc",
    StepEnum.FILLER.value: "filler_ecc",
    StepEnum.RCX.value: "RCX_ecc",
    StepEnum.STA.value: "sta_ecc",
    StepEnum.LVS.value: "lvs_ecc",
    SkippableStepEnum.POST_ROUTE_LEC.value: "postRouteLec_kepler_formal",
    StepEnum.DRC.value: "drc_ecc",
    StepEnum.HARDEN.value: "Harden_ecc",
}

# Directories of retired LEC engines. Workspaces whose ledger still records
# them keep resolving artifacts under these names.
LEGACY_STEP_DIRECTORIES = {
    SkippableStepEnum.LEC.value: "lec_yosys_lec",
    SkippableStepEnum.POST_ROUTE_LEC.value: "postRouteLec_yosys_lec",
}

# Directories of the dual cross-checking LEC engine. Like the legacy
# single-engine directories, they resolve only through tool-aware lookup —
# the name-keyed table alone cannot tell which engine a ledger recorded.
DUAL_STEP_DIRECTORIES = {
    SkippableStepEnum.LEC.value: "lec_dual",
    SkippableStepEnum.POST_ROUTE_LEC.value: "postRouteLec_dual",
}


def step_directory_for_tool(step_name: str, tool: str | None) -> str:
    """Resolve a step directory for the engine the flow recorded.

    LEC steps own one directory per engine (yosys_lec historically,
    kepler_formal today, lec_dual for cross-checking); every other step
    has a single directory.
    """
    if tool == "yosys_lec" and step_name in LEGACY_STEP_DIRECTORIES:
        return LEGACY_STEP_DIRECTORIES[step_name]
    if tool == "lec_dual" and step_name in DUAL_STEP_DIRECTORIES:
        return DUAL_STEP_DIRECTORIES[step_name]
    return STEP_DIRECTORIES.get(step_name, f"{step_name}_{tool}")


def all_step_directories() -> list[str]:
    """Current and legacy step directories, deduplicated in stable order.

    Directory scans (checklist aggregation, report extraction) iterate this so
    workspaces from either LEC-engine generation are covered.
    """
    return list(
        dict.fromkeys(
            [
                *STEP_DIRECTORIES.values(),
                *LEGACY_STEP_DIRECTORIES.values(),
                *DUAL_STEP_DIRECTORIES.values(),
            ]
        )
    )


def flow_step_directory(steps: list[dict] | None, step_name: str) -> str:
    """Resolve a step directory from a flow ledger's (name, tool) records."""
    for step in steps or []:
        if isinstance(step, dict) and step.get("name") == step_name:
            return step_directory_for_tool(step_name, str(step.get("tool", "")) or None)
    return STEP_DIRECTORIES.get(step_name, step_name)


def inactive_lec_step_directories(steps: list[dict] | None) -> frozenset:
    """LEC step directories holding stale evidence for a flow ledger.

    LEC steps own one directory per engine; after an engine switch the
    previous engine's directory is preserved evidence, never current
    state. Returns every engine's directory for lec/postRouteLec except
    the one the ledger recorded (per step); when the ledger lacks a LEC
    step, all of that step's engine directories count as inactive.
    """
    from chipcompiler.data.types import LEC_STEP_TOOLS

    lec_names = {SkippableStepEnum.LEC.value, SkippableStepEnum.POST_ROUTE_LEC.value}
    ledger_names = {str(step.get("name", "")) for step in steps or [] if isinstance(step, dict)}
    active = {flow_step_directory(steps, name) for name in lec_names & ledger_names}
    return (
        frozenset(
            step_directory_for_tool(name, tool) for name in lec_names for tool in LEC_STEP_TOOLS
        )
        - active
    )


def step_storage_name(step_name: str, tool_name: str) -> str:
    """Directory stem for ``{stem}_{tool}`` workspace step folders.

    Sizer stores Timing Opt as ``timing_optimization_sizer`` instead of
    ``Timing optimization_sizer``. Other tools keep the flow step name.
    """
    if tool_name.lower() == "sizer":
        return "_".join(step_name.split()).lower()
    return step_name


###########################################################################
# step definition for chip design flow in json format
# step_definition =
# {
#     "name" : "", # step name
#     "tool" : "", # eda tool name
#     "state" : "", # step state
#     "runtime" : "", # step run time
#     "info" : {} # step additional infomation
# }
###########################################################################


@dataclass
class StepMetrics:
    """
    Dataclass for step metrics
    """

    path: str | Path = ""  # metrics file path
    data: dict = field(default_factory=dict)  # metrics data
    report: list = field(default_factory=list)  # metrics report


###########################################################################
# step metrics definition in json format
# step_metrics =
# {
#     "name" : "", # step name
#     "tool" : "", # eda tool name
# }
###########################################################################


def load_metrics(path: str | Path) -> StepMetrics:
    from chipcompiler.utility import json_read

    metrics = StepMetrics()
    metrics.path = path
    metrics.data = json_read(path)
    return metrics


def save_metrics(metrics: StepMetrics) -> bool:
    from chipcompiler.utility import json_write

    return json_write(file_path=metrics.path, data=metrics.data)
