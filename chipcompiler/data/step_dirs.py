"""Canonical workspace step-directory names.

Workspace creation names each step directory ``<step>_<tool>`` along the
canonical rtl2gds chain (``Synthesis_yosys``, ``place_dreamplace``, ...).
Checklists, signoff packages, QoR scoring, and the design reports all
resolve per-step artifacts through that naming, so the mapping lives here
once instead of as hand-maintained tables per consumer. Timing
optimization is on the canonical chain but owns no artifact directory any
consumer reads through these tables.
"""

from chipcompiler.data.step import StepEnum

STEP_DIRECTORIES = {
    StepEnum.SYNTHESIS.value: "Synthesis_yosys",
    StepEnum.LEC.value: "lec_kepler_formal",
    StepEnum.FLOORPLAN.value: "Floorplan_ecc",
    StepEnum.PLACEMENT.value: "place_dreamplace",
    StepEnum.CTS.value: "CTS_ecc",
    StepEnum.LEGALIZATION.value: "legalization_dreamplace",
    StepEnum.ROUTING.value: "route_ecc",
    StepEnum.FILLER.value: "filler_ecc",
    StepEnum.RCX.value: "RCX_ecc",
    StepEnum.STA.value: "sta_ecc",
    StepEnum.LVS.value: "lvs_ecc",
    StepEnum.POST_ROUTE_LEC.value: "postRouteLec_kepler_formal",
    StepEnum.DRC.value: "drc_ecc",
    StepEnum.HARDEN.value: "Harden_ecc",
}

# Directories of retired LEC engines. Workspaces whose ledger still records
# them keep resolving artifacts under these names.
LEGACY_STEP_DIRECTORIES = {
    StepEnum.LEC.value: "lec_yosys_lec",
    StepEnum.POST_ROUTE_LEC.value: "postRouteLec_yosys_lec",
}


def step_directory_for_tool(step_name: str, tool: str | None) -> str:
    """Resolve a step directory for the engine the flow recorded.

    LEC steps own one directory per engine (yosys_lec historically,
    kepler_formal today); every other step has a single directory.
    """
    if tool == "yosys_lec" and step_name in LEGACY_STEP_DIRECTORIES:
        return LEGACY_STEP_DIRECTORIES[step_name]
    return STEP_DIRECTORIES.get(step_name, f"{step_name}_{tool}")


def all_step_directories() -> list[str]:
    """Current and legacy step directories, deduplicated in stable order.

    Directory scans (checklist aggregation, report extraction) iterate this so
    workspaces from either LEC-engine generation are covered.
    """
    return list(dict.fromkeys([*STEP_DIRECTORIES.values(), *LEGACY_STEP_DIRECTORIES.values()]))


def flow_step_directory(steps: list[dict] | None, step_name: str) -> str:
    """Resolve a step directory from a flow ledger's (name, tool) records."""
    for step in steps or []:
        if isinstance(step, dict) and step.get("name") == step_name:
            return step_directory_for_tool(step_name, str(step.get("tool", "")) or None)
    return STEP_DIRECTORIES.get(step_name, step_name)
