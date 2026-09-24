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


class LECEngineEnum(Enum):
    """Engines that can own the lec/postRouteLec steps.

    DUAL is a composite: it runs both physical engines on the same inputs
    and aggregates their verdicts.
    """

    YOSYS_LEC = "yosys_lec"
    KEPLER_FORMAL = "kepler_formal"
    DUAL = "lec_dual"

    @classmethod
    def from_value(cls, raw: object) -> "LECEngineEnum":
        """The LEC engine for a persisted/declared spelling.

        Accepts every member value plus the ``dual`` alias (normalized to
        ``lec_dual``); anything else raises ValueError listing the legal
        set. Persisted and ledger strings always use the member value,
        never the alias.
        """
        if isinstance(raw, cls):
            return raw
        token = str(raw or "").strip()
        if token == "dual":
            return cls.DUAL
        try:
            return cls(token)
        except ValueError:
            legal = ", ".join(sorted(member.value for member in cls))
            raise ValueError(
                f"unknown LEC engine: {raw!r}; available engines: {legal} (or the 'dual' alias)"
            ) from None

    @property
    def spawn_engines(self) -> tuple["LECEngineEnum", ...]:
        """The physical engines to probe/launch (DUAL fans out)."""
        if self is LECEngineEnum.DUAL:
            return (LECEngineEnum.YOSYS_LEC, LECEngineEnum.KEPLER_FORMAL)
        return (self,)


# Tool identifiers that can own the lec/postRouteLec steps. Workspaces keep
# the engine their ledger recorded, so every LEC-aware branch (input wiring,
# result checks, DB skips) matches this set instead of one literal.
LEC_STEP_TOOLS: Final = frozenset(member.value for member in LECEngineEnum)

DEFAULT_LEC_ENGINE: Final = LECEngineEnum.KEPLER_FORMAL


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
