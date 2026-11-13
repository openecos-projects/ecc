# pyright: strict
"""``plan_flow``: the steps a selection runs, and whether they can run.

A step selection is a preset chain minus its skipped steps (``[flow]
skip_steps``) plus its inserted steps (``[flow] insert_steps``, an LEC after a
design-building step); any step may be skipped when the remaining steps still
get the design data they require. An inserted step runs exactly when the step
it follows runs. The plan checks the enabled steps with :func:`check_flow`.

The design data present before the first enabled step is what the chain
would have produced up to that step. A flow entering mid-chain reads the
project's declared inputs instead, and those are validated per entry step
(``cli/project/design_inputs.required_inputs_for_step``), so they stand in
for the steps before it.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from chipcompiler.data.flow_check import FlowViolation, Severity, check_flow, design_data_after
from chipcompiler.data.types import (
    DEFAULT_LEC_ENGINE,
    DesignData,
    DesignState,
    LECEngineEnum,
    SkippableStepEnum,
    StepBaseEnum,
)

#: The design data a preset chain starts from.
_CHAIN_INPUT: frozenset[DesignData] = frozenset({DesignState.RTL})
_OPTIONAL_STEPS = frozenset(member.value for member in SkippableStepEnum)

#: One chain entry: canonical step name and tool.
ChainStep = tuple[str, str]


@dataclass(frozen=True, slots=True)
class PlannedStep:
    name: str
    tool: str
    enabled: bool
    #: Optional by design (:class:`SkippableStepEnum`): downstream steps never
    #: need its outputs, so skipping it cannot fail the flow.
    optional: bool
    #: Inserted after the step before it (``[flow] insert_steps``); enabled
    #: exactly when that step is.
    inserted: bool = False


@dataclass(frozen=True, slots=True)
class PlanViolation:
    step: str
    severity: Severity
    missing: frozenset[DesignData]
    #: Disabled steps, nearest first, whose enabling supplies part of ``missing``.
    fixes: tuple[str, ...]

    @property
    def missing_names(self) -> tuple[str, ...]:
        """``missing`` as sorted plain names, for records and messages."""
        return tuple(sorted(str(item) for item in self.missing))

    def message(self) -> str:
        missing = ", ".join(self.missing_names)
        match self.severity:
            case Severity.ERROR:
                text = f"{self.step} requires {missing}"
            case Severity.WARNING:
                text = f"{self.step} runs with degraded results without {missing}"
        if self.fixes:
            text += f"; enable {' or '.join(self.fixes)}"
        return text


@dataclass(frozen=True, slots=True)
class FlowPlan:
    steps: tuple[PlannedStep, ...]
    #: Design data present before the first enabled step.
    available: frozenset[DesignData]
    violations: tuple[PlanViolation, ...]

    @property
    def enabled_steps(self) -> tuple[str, ...]:
        return tuple(step.name for step in self.steps if step.enabled)

    @property
    def skip_steps(self) -> tuple[str, ...]:
        """The skipped chain steps; an inserted step is never skipped, only removed."""
        return tuple(step.name for step in self.steps if not step.enabled and not step.inserted)

    @property
    def insert_steps(self) -> tuple[str, ...]:
        return tuple(step.name for step in self.steps if step.inserted)

    @property
    def errors(self) -> tuple[PlanViolation, ...]:
        return tuple(item for item in self.violations if item.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[PlanViolation, ...]:
        return tuple(item for item in self.violations if item.severity is Severity.WARNING)


def preset_chain(
    preset: str, *, lec_engine: LECEngineEnum | str = DEFAULT_LEC_ENGINE
) -> tuple[ChainStep, ...]:
    """The full step chain of *preset*, LEC steps bound to *lec_engine*."""
    from chipcompiler import rtl2gds as rtl2gds_api

    builder = rtl2gds_api.get_flow_builders().get(preset)
    if builder is None:
        raise ValueError(f"unknown flow preset: {preset!r}")
    return tuple(
        (step.value if isinstance(step, StepBaseEnum) else str(step), str(tool))
        for step, tool, _state in rtl2gds_api.substitute_lec_engine(builder(), lec_engine)
    )


def flow_target(chain: Sequence[ChainStep]) -> str:
    """The step *chain* ends with: its last step that is not an inserted check."""
    from chipcompiler.rtl2gds import parse_inserted_step

    return next(name for name, _tool in reversed(chain) if parse_inserted_step(name) is None)


def inserted_chain(
    insert_steps: Sequence[str], *, lec_engine: LECEngineEnum | str = DEFAULT_LEC_ENGINE
) -> tuple[ChainStep, ...]:
    """Canonical inserted step names with their tools (inserted LECs use *lec_engine*)."""
    tool = LECEngineEnum.from_value(lec_engine).value
    return tuple((name, tool) for name in insert_steps)


def plan_flow(
    chain: Sequence[ChainStep],
    *,
    skip_steps: Collection[str] = (),
    inserted: Sequence[ChainStep] = (),
    start: str | None = None,
    end: str | None = None,
) -> FlowPlan:
    """Plan *chain* from *start* to *end* (inclusive) without *skip_steps*.

    Names are canonical step names. *inserted* are canonical inserted steps
    (``lec@CTS``) with their tools; each follows its step, the range's last
    step included, and one whose step is outside the range is left out. A
    chain may build an inserted step itself (``synthesis_lec``:
    ``lec@Synthesis``); it is planned the same way. *start* and *end* default
    to the ends of the chain; skip names outside the planned range are
    ignored. The flow target (:func:`flow_target`) and an explicit *start*,
    where the flow was asked to begin, may not be skipped; the first step of
    a whole chain may be (the declared inputs then stand in for it). Raises
    ``ValueError`` for a boundary outside the chain, a reversed range or a
    skipped boundary.
    """
    names = [name for name, _tool in chain]
    for boundary in (start, end):
        if boundary is not None and boundary not in names:
            raise ValueError(
                f"unknown flow step: {boundary!r}; available steps: {', '.join(names)}"
            )
    first = names.index(start) if start is not None else 0
    last = names.index(end) if end is not None else len(names) - 1
    if first > last:
        raise ValueError(f"flow range is reversed: {start!r} -> {end!r}")

    skipped = set(skip_steps)
    if (target := flow_target(chain[first : last + 1])) in skipped:
        raise ValueError(f"{target!r} ends the flow and cannot be skipped")
    if start is not None and start in skipped:
        raise ValueError(f"{start!r} starts the flow range and cannot be skipped")
    steps = _with_inserted(_chain_steps(chain[first : last + 1], skipped), inserted)
    enabled = [step.name for step in steps if step.enabled]
    return FlowPlan(
        steps=steps,
        available=_available_before(names, enabled[0]),
        violations=tuple(
            _with_fixes(violation, steps, names) for violation in _check(enabled, names)
        ),
    )


def _chain_steps(chain: Sequence[ChainStep], skipped: set[str]) -> tuple[PlannedStep, ...]:
    from chipcompiler.rtl2gds import parse_inserted_step

    steps: list[PlannedStep] = []
    for name, tool in chain:
        if (parsed := parse_inserted_step(name)) is None:
            steps.append(
                PlannedStep(
                    name, tool, enabled=name not in skipped, optional=name in _OPTIONAL_STEPS
                )
            )
            continue
        anchor = next((step for step in steps if step.name == parsed[1]), None)
        enabled = anchor is not None and anchor.enabled
        steps.append(PlannedStep(name, tool, enabled, optional=True, inserted=True))
    return tuple(steps)


def _with_inserted(
    steps: tuple[PlannedStep, ...], inserted: Sequence[ChainStep]
) -> tuple[PlannedStep, ...]:
    from chipcompiler.rtl2gds import parse_inserted_step

    following: dict[str, ChainStep] = {}
    for name, tool in inserted:
        parsed = parse_inserted_step(name)
        if parsed is None:
            raise ValueError(f"not an inserted step: {name!r}")
        following[parsed[1]] = (name, tool)
    names = {step.name for step in steps}
    result: list[PlannedStep] = []
    for step in steps:
        result.append(step)
        # A preset may build the inserted step itself (synthesis_lec: lec@Synthesis).
        if step.name in following and following[step.name][0] not in names:
            name, tool = following[step.name]
            result.append(PlannedStep(name, tool, step.enabled, optional=True, inserted=True))
    return tuple(result)


def _available_before(chain_names: Sequence[str], entry: str) -> frozenset[DesignData]:
    return design_data_after(chain_names[: chain_names.index(entry)], available=_CHAIN_INPUT)


def _check(enabled: Sequence[str], chain_names: Sequence[str]) -> tuple[FlowViolation, ...]:
    return check_flow(enabled, available=_available_before(chain_names, enabled[0]))


def _with_fixes(
    violation: FlowViolation, steps: Sequence[PlannedStep], chain_names: Sequence[str]
) -> PlanViolation:
    position = next(index for index, step in enumerate(steps) if step.name == violation.step)
    fixes: list[str] = []
    for candidate in reversed(steps[:position]):
        if candidate.enabled:
            continue
        trial = [step.name for step in steps if step.enabled or step is candidate]
        remaining = next(
            (
                item.missing
                for item in _check(trial, chain_names)
                if item.step == violation.step and item.severity is violation.severity
            ),
            frozenset[DesignData](),
        )
        if remaining < violation.missing:
            fixes.append(candidate.name)
    return PlanViolation(violation.step, violation.severity, violation.missing, tuple(fixes))
