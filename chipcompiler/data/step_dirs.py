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
    StepEnum.LEC.value: "lec_yosys_lec",
    StepEnum.FLOORPLAN.value: "Floorplan_ecc",
    StepEnum.PLACEMENT.value: "place_dreamplace",
    StepEnum.CTS.value: "CTS_ecc",
    StepEnum.LEGALIZATION.value: "legalization_dreamplace",
    StepEnum.ROUTING.value: "route_ecc",
    StepEnum.DRC.value: "drc_ecc",
    StepEnum.LVS.value: "lvs_ecc",
    StepEnum.FILLER.value: "filler_ecc",
    StepEnum.POST_ROUTE_LEC.value: "postRouteLec_yosys_lec",
    StepEnum.RCX.value: "RCX_ecc",
    StepEnum.STA.value: "sta_ecc",
    StepEnum.HARDEN.value: "Harden_ecc",
}
