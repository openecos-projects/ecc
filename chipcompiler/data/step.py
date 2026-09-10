#!/usr/bin/env python

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class StepEnum(Enum):
    """RTL2GDS flow step names"""

    RTL2GDS = "RTL2GDS"
    INIT = "Init"
    SYNTHESIS = "Synthesis"
    FLOORPLAN = "Floorplan"
    PLACEMENT = "place"
    CTS = "CTS"
    TIMING_OPT = "Timing optimization"
    LEGALIZATION = "legalization"
    ROUTING = "route"
    FILLER = "filler"
    GDS = "GDS"
    SIGNOFF = "Signoff"
    LEC = "lec"
    POST_ROUTE_LEC = "postRouteLec"
    STA = "sta"
    DRC = "drc"
    LVS = "lvs"
    RCX = "RCX"
    ABSTRACT_LEF = "Abstract lef"
    HARDEN = "Harden"


class StateEnum(Enum):
    """flow running state"""

    Invalid = "Invalid"  # ecc tools or config invalid
    Unstart = "Unstart"  # step unstart
    Success = "Success"  # step run success
    Ongoing = "Ongoing"  # step is running
    Pending = "Pending"  # step is pending
    Imcomplete = "Incomplete"  # step is failed
    # Ignored = "Ignored" # step result do not affect flow step


FINISHED_STEP_STATES = frozenset({StateEnum.Success.value})


def step_storage_name(step_name: str, tool_name: str) -> str:
    """Directory stem for ``{stem}_{tool}`` workspace step folders.

    Sizer stores Timing Opt as ``timing_optimization_sizer`` instead of
    ``Timing optimization_sizer``. Other tools keep the flow step name.
    """
    if tool_name.lower() == "sizer":
        return "_".join(step_name.split()).lower()
    return step_name


def is_finished_step_state(state: object) -> bool:
    """Whether a persisted step state counts as done for selection and skipping.

    Incomplete/Invalid steps are unfinished: resume and rerun selectors
    re-execute them. A legacy ``Warning`` state (removed terminal state for
    the synthesis LEC) is not finished and is normalized to Unstart on
    resume.
    """
    return state in FINISHED_STEP_STATES


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
