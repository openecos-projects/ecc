"""``check_flow``: does a step order supply the design data every step needs?

Each step adds the design data it provides, and its placement legality decides
whether the placement is legal afterwards; nothing else is ever taken away.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from chipcompiler.data.types import DesignData, DesignState, PlacementLegality, flow_step_policy


class Severity(StrEnum):
    #: Required design data is missing: the step cannot run.
    ERROR = "error"
    #: Optional design data is missing: the step runs with degraded results.
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class FlowViolation:
    step: str
    severity: Severity
    missing: frozenset[DesignData]


def check_flow(
    steps: Iterable[str], *, available: Iterable[DesignData]
) -> tuple[FlowViolation, ...]:
    """Every violation along *steps*, in flow order.

    *available* is the design data present before the first step, for example
    ``{DesignState.RTL}`` for a flow that starts at synthesis. An unknown step
    name raises ``ValueError``.
    """
    present: set[DesignData] = set(available)
    violations: list[FlowViolation] = []
    for step in steps:
        policy = flow_step_policy(step)
        if missing := policy.requires - present:
            violations.append(FlowViolation(step, Severity.ERROR, missing))
        if missing_optional := policy.uses - present:
            violations.append(FlowViolation(step, Severity.WARNING, missing_optional))
        _advance(step, present)
    return tuple(violations)


def design_states_after(step: str, states: Iterable[DesignState]) -> frozenset[DesignState]:
    """The design states the output design of *step* carries.

    *states* are the states of the design the step read. An unknown step name
    raises ``ValueError``.
    """
    present: set[DesignData] = set(states)
    _advance(step, present)
    return frozenset(item for item in present if isinstance(item, DesignState))


def _advance(step: str, present: set[DesignData]) -> None:
    policy = flow_step_policy(step)
    present |= policy.provides
    match policy.legality:
        case PlacementLegality.LEGALIZED:
            present.add(DesignState.LEGAL)
        case PlacementLegality.NEEDS_LEGALIZATION:
            present.discard(DesignState.LEGAL)
        case PlacementLegality.UNCHANGED:
            pass
