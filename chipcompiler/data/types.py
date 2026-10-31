"""Flow step and state vocabulary: enums plus enum-only pure predicates.

Zero IO and zero chipcompiler-internal imports: this module is the
dependency-free root of the data layer's type vocabulary.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class FlowStepCategory(StrEnum):
    """Input chaining behavior for persisted flow steps."""

    PNR = "PNR"
    CHECKER = "CHECKER"


class StepBaseEnum(StrEnum):
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
    PREPLACE = "preplace"
    PLACEMENT = "place"
    DIFF_BUFFERING = "diff_buffering"
    DIFF_SIZING = "diff_sizing"
    LEGALIZATION = "legalization"
    ROUTING = "route"
    FILLER = "filler"
    GDS = "GDS"
    SIGNOFF = "Signoff"
    STA = "sta"
    DRC = "drc"
    ANTENNA_CHECK = "antennaCheck"
    LVS = "lvs"
    RCX = "RCX"
    POWER_ANALYSIS = "powerAnalysis"
    EMIR = "emir"
    ABSTRACT_LEF = "Abstract lef"
    HARDEN = "Harden"
    DEFVIEW = "defview"


class SkippableStepEnum(StepBaseEnum):
    """Optional flow steps a project may exclude from its ledger.

    LEC / postRouteLec / Timing optimization are check/optimization steps
    whose outputs downstream steps can do without. CTS is also skippable,
    but only when ``flow.no_clock`` is set — ``resolve_skip_steps`` enforces
    that gate so a clocked design cannot drop CTS by accident. Persisted
    string values match the former StepEnum members.
    """

    LEC = "lec"
    DIFF_OPT = "diff_opt"
    POST_ROUTE_LEC = "postRouteLec"
    TIMING_OPT = "Timing optimization"
    CTS = "CTS"

    def is_skippable(self) -> bool:
        return True


class FlowInputSource(StrEnum):
    """Where a step's declared input comes from when no explicit input is set."""

    #: The previous non-LEC, non-advisory step in ledger order.
    PREVIOUS = "previous"
    #: The step before the parallel checker batch anchored at ``filler``.
    CHECKER_BATCH = "checker_batch"
    #: The output of ``filler`` for physical signoff analyses.
    FILLER = "filler"


@dataclass(frozen=True)
class FlowStepPolicy:
    """The flow's knowledge about one step: category and input source.

    ``advisory`` steps keep their execution state but neither gate the flow nor
    become the source of physical design artifacts for downstream steps.
    ``input_source`` declares the default edge; an explicit ledger
    ``input_step`` still overrides it.
    """

    category: FlowStepCategory
    input_source: FlowInputSource = FlowInputSource.PREVIOUS
    advisory: bool = False


# Every flow step is declared here; a step missing from this table fails the
# exhaustiveness test instead of silently inheriting the PNR default.
FLOW_STEP_POLICIES: Final[dict[str, FlowStepPolicy]] = {
    StepEnum.RTL2GDS.value: FlowStepPolicy(FlowStepCategory.PNR),
    StepEnum.INIT.value: FlowStepPolicy(FlowStepCategory.PNR),
    StepEnum.SYNTHESIS.value: FlowStepPolicy(FlowStepCategory.PNR),
    StepEnum.FLOORPLAN.value: FlowStepPolicy(FlowStepCategory.PNR),
    StepEnum.PRE_FLOORPLAN.value: FlowStepPolicy(FlowStepCategory.PNR),
    StepEnum.MACRO_PLACEMENT.value: FlowStepPolicy(FlowStepCategory.PNR),
    StepEnum.POST_FLOORPLAN.value: FlowStepPolicy(FlowStepCategory.PNR),
    StepEnum.PREPLACE.value: FlowStepPolicy(FlowStepCategory.PNR),
    StepEnum.PLACEMENT.value: FlowStepPolicy(FlowStepCategory.PNR),
    StepEnum.DIFF_BUFFERING.value: FlowStepPolicy(FlowStepCategory.PNR),
    SkippableStepEnum.DIFF_OPT.value: FlowStepPolicy(FlowStepCategory.PNR),
    StepEnum.DIFF_SIZING.value: FlowStepPolicy(FlowStepCategory.PNR),
    SkippableStepEnum.CTS.value: FlowStepPolicy(FlowStepCategory.PNR),
    StepEnum.LEGALIZATION.value: FlowStepPolicy(FlowStepCategory.PNR),
    StepEnum.ROUTING.value: FlowStepPolicy(FlowStepCategory.PNR),
    StepEnum.FILLER.value: FlowStepPolicy(FlowStepCategory.PNR),
    StepEnum.LVS.value: FlowStepPolicy(FlowStepCategory.CHECKER, FlowInputSource.CHECKER_BATCH),
    StepEnum.DRC.value: FlowStepPolicy(FlowStepCategory.CHECKER, FlowInputSource.CHECKER_BATCH),
    StepEnum.ANTENNA_CHECK.value: FlowStepPolicy(
        FlowStepCategory.CHECKER, FlowInputSource.FILLER, advisory=True
    ),
    SkippableStepEnum.POST_ROUTE_LEC.value: FlowStepPolicy(
        FlowStepCategory.CHECKER, FlowInputSource.FILLER
    ),
    StepEnum.RCX.value: FlowStepPolicy(FlowStepCategory.CHECKER, FlowInputSource.FILLER),
    StepEnum.STA.value: FlowStepPolicy(FlowStepCategory.CHECKER, FlowInputSource.FILLER),
    StepEnum.POWER_ANALYSIS.value: FlowStepPolicy(FlowStepCategory.CHECKER, FlowInputSource.FILLER),
    StepEnum.EMIR.value: FlowStepPolicy(
        FlowStepCategory.CHECKER, FlowInputSource.FILLER, advisory=True
    ),
    StepEnum.HARDEN.value: FlowStepPolicy(FlowStepCategory.PNR, FlowInputSource.FILLER),
    StepEnum.SIGNOFF.value: FlowStepPolicy(FlowStepCategory.PNR),
    StepEnum.GDS.value: FlowStepPolicy(FlowStepCategory.PNR),
    StepEnum.ABSTRACT_LEF.value: FlowStepPolicy(FlowStepCategory.PNR),
    SkippableStepEnum.LEC.value: FlowStepPolicy(FlowStepCategory.PNR),
    SkippableStepEnum.TIMING_OPT.value: FlowStepPolicy(FlowStepCategory.PNR),
    StepEnum.DEFVIEW.value: FlowStepPolicy(FlowStepCategory.PNR),
}

ADVISORY_FLOW_STEPS: Final = frozenset(
    name for name, policy in FLOW_STEP_POLICIES.items() if policy.advisory
)

FLOW_STEP_CATEGORIES: Final[dict[str, FlowStepCategory]] = {
    name: policy.category for name, policy in FLOW_STEP_POLICIES.items()
}


def flow_step_policy(step: StepBaseEnum | str) -> FlowStepPolicy:
    """The registered policy for a flow step; unknown names raise."""
    value = step.value if isinstance(step, StepBaseEnum) else str(step)
    try:
        return FLOW_STEP_POLICIES[value]
    except KeyError:
        raise ValueError(f"no flow policy registered for step: {value!r}") from None


def default_flow_step_category(step: StepBaseEnum | str) -> FlowStepCategory:
    """The category for a declared step name, with a PNR fallback.

    Ledger walks use :func:`flow_step_policy` instead, so a step added
    without a policy fails loudly rather than silently inheriting PNR.
    """
    value = step.value if isinstance(step, StepBaseEnum) else str(step)
    policy = FLOW_STEP_POLICIES.get(value)
    return policy.category if policy is not None else FlowStepCategory.PNR


# New flows skip synthesis LEC and placement-parasitic diff_opt by default.
# An explicit skip list replaces this policy; existing ledgers are preserved.
DEFAULT_SKIP_STEPS: Final = (SkippableStepEnum.LEC.value, SkippableStepEnum.DIFF_OPT.value)


class ToolName(StrEnum):
    """Tool names a flow step (or the image backend) can bind to."""

    YOSYS = "yosys"
    ECC = "ecc"
    DREAMPLACE = "dreamplace"
    SIZER = "sizer"
    YOSYS_LEC = "yosys_lec"
    KEPLER_FORMAL = "kepler_formal"
    LEC_DUAL = "lec_dual"
    # Not a flow-step tool: the layout-image backend behind save_layout_image.
    KLAYOUT = "klayout"


class LECEngineEnum(StrEnum):
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


def is_sta_step(step: object) -> bool:
    """Whether *step* is the ECC static-timing step (the only parallel one)."""
    return (
        getattr(step, "tool", None) == ToolName.ECC
        and getattr(step, "name", None) == StepEnum.STA.value
    )


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


class StateEnum(StrEnum):
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
