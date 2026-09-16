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
    SkippableStepEnum.LEC.value: "lec_yosys_lec",
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
    SkippableStepEnum.POST_ROUTE_LEC.value: "postRouteLec_yosys_lec",
    StepEnum.DRC.value: "drc_ecc",
    StepEnum.HARDEN.value: "Harden_ecc",
}


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
