"""Flow step and state vocabulary: enums plus enum-only pure predicates.

Zero IO and zero chipcompiler-internal imports: this module is the
dependency-free root of the data layer's type vocabulary.
"""

from enum import Enum


class StepEnum(Enum):
    """RTL2GDS flow step names"""

    RTL2GDS = "RTL2GDS"
    INIT = "Init"
    SYNTHESIS = "Synthesis"
    FLOORPLAN = "Floorplan"  # shared floorplan configuration key, not a flow step
    PRE_FLOORPLAN = "preFloorplan"
    MACRO_PLACEMENT = "macroPlacement"
    POST_FLOORPLAN = "postFloorplan"
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


def is_finished_step_state(state: object) -> bool:
    """Whether a persisted step state counts as done for selection and skipping.

    Incomplete/Invalid steps are unfinished: resume and rerun selectors
    re-execute them. A legacy ``Warning`` state (removed terminal state for
    the synthesis LEC) is not finished and is normalized to Unstart on
    resume.
    """
    return state in FINISHED_STEP_STATES
