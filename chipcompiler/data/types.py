"""Flow step and state vocabulary: enums plus enum-only pure predicates.

Zero IO and zero chipcompiler-internal imports: this module is the
dependency-free root of the data layer's type vocabulary.
"""

from enum import Enum
from typing import Final


class StepBaseEnum(Enum):
    """Memberless base of the flow step enums: shared behavior.

    Python forbids inheriting an Enum that has members, so shared step
    behavior lives on this base while the concrete members are split
    between :class:`StepEnum` (core chain steps) and
    :class:`SkippableStepEnum` (optional steps a project may exclude).
    """

    def is_skippable(self) -> bool:
        return False


class StepEnum(StepBaseEnum):
    """RTL2GDS flow step names (core chain steps)"""

    RTL2GDS = "RTL2GDS"
    INIT = "Init"
    SYNTHESIS = "Synthesis"
    FLOORPLAN = "Floorplan"  # shared floorplan configuration key, not a flow step
    PRE_FLOORPLAN = "preFloorplan"
    MACRO_PLACEMENT = "macroPlacement"
    POST_FLOORPLAN = "postFloorplan"
    PLACEMENT = "place"
    CTS = "CTS"
    LEGALIZATION = "legalization"
    ROUTING = "route"
    FILLER = "filler"
    GDS = "GDS"
    SIGNOFF = "Signoff"
    STA = "sta"
    DRC = "drc"
    LVS = "lvs"
    RCX = "RCX"
    ABSTRACT_LEF = "Abstract lef"
    HARDEN = "Harden"


class SkippableStepEnum(StepBaseEnum):
    """Optional flow steps a project may exclude from its ledger.

    These are check/optimization steps whose outputs downstream steps can
    do without; persisted string values match the former StepEnum members.
    """

    LEC = "lec"
    POST_ROUTE_LEC = "postRouteLec"
    TIMING_OPT = "Timing optimization"

    def is_skippable(self) -> bool:
        return True


# Projects that declare no skip policy skip the synthesis LEC: the
# conservative default keeps pre-existing projects' ledgers unchanged.
# An explicit empty skip list is the only way to enable it.
DEFAULT_SKIP_STEPS: Final = (SkippableStepEnum.LEC.value,)


_STEP_ENUMS: tuple[type[StepBaseEnum], ...] = (StepEnum, SkippableStepEnum)


def step_from_value(name: str) -> StepBaseEnum:
    """The step enum member for a persisted step value, across both enums.

    Raises ValueError for an unknown value, mirroring ``StepEnum(name)``.
    """
    for enum in _STEP_ENUMS:
        try:
            return enum(name)
        except ValueError:
            continue
    legal = ", ".join(sorted(member.value for enum in _STEP_ENUMS for member in enum))
    raise ValueError(f"unknown flow step: {name!r}; available steps: {legal}")


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
