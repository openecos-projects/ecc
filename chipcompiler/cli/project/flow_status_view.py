# pyright: strict
"""The typed view of a project's step selection, and its record form.

``ecc flow status`` reports :class:`StatusView` as records (``--json``/``--plain``);
the rich table and the ``ecc flow edit`` checkbox draw the view itself. Records
read back through :func:`view_from_records` are checked field by field.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast

from chipcompiler.data.flow_check import Severity
from chipcompiler.data.flow_needs import StepNeeds, plan_needs
from chipcompiler.data.flow_plan import FlowPlan, PlannedStep
from chipcompiler.data.flow_stages import StepStage, plan_stages
from chipcompiler.data.types import (
    DesignState,
    FlowStepCategory,
    PlacementLegality,
    flow_step_policy,
)

ProblemKind = Literal["flow_violation", "flow_input"]
ProblemSeverity = Literal["error", "warning"]
PlanStatus = Literal["ok", "warning", "error"]
Record = dict[str, object]


@dataclass(frozen=True, slots=True)
class StepRow:
    position: int
    step: str
    tool: str
    enabled: bool
    optional: bool
    #: The flow's final step: it cannot be skipped.
    target: bool
    requires: tuple[str, ...]
    uses: tuple[str, ...]
    provides: tuple[str, ...]
    #: Steps of one stage can run in parallel; ``label`` is ``stage`` plus ``slot``.
    #: A disabled step has no stage (``None``, empty ``slot`` and ``label``).
    stage: int | None
    slot: str
    label: str
    parallel_with: tuple[str, ...]
    #: Producers the step follows, nearest first (see :class:`StepNeeds`).
    after: tuple[str, ...]
    #: Capability -> producer step (``None``: no enabled step provides it).
    needs: tuple[tuple[str, str | None], ...]
    #: A checker that provides nothing: it only reports.
    check: bool
    #: Inserted after the step before it (``[flow] insert_steps``); enabled
    #: exactly when that step is.
    inserted: bool


@dataclass(frozen=True, slots=True)
class PlanProblem:
    """Missing design data (``flow_violation``) or an undeclared entry input
    (``flow_input``)."""

    kind: ProblemKind
    severity: ProblemSeverity
    step: str
    reason: str
    missing: tuple[str, ...] = ()
    fixes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StatusView:
    flow: str
    steps: tuple[StepRow, ...]
    problems: tuple[PlanProblem, ...]
    #: The project's ``[flow] max_parallel_steps``: at most this many steps of
    #: one stage run at once.
    max_parallel_steps: int

    @property
    def enabled_count(self) -> int:
        return sum(step.enabled for step in self.steps)

    @property
    def skip_steps(self) -> tuple[str, ...]:
        return tuple(step.step for step in self.steps if not step.enabled and not step.inserted)

    @property
    def insert_steps(self) -> tuple[str, ...]:
        return tuple(step.step for step in self.steps if step.inserted)

    @property
    def status(self) -> PlanStatus:
        severities = {problem.severity for problem in self.problems}
        return "error" if "error" in severities else "warning" if severities else "ok"

    @property
    def blocks_saving(self) -> bool:
        """Whether a step lacks required design data (inputs can be declared later)."""
        return any(
            problem.kind == "flow_violation" and problem.severity == "error"
            for problem in self.problems
        )


def status_view(
    plan: FlowPlan, *, flow: str, max_parallel_steps: int, input_errors: Sequence[str] = ()
) -> StatusView:
    """The view of *plan*; *input_errors* are entry inputs ``ecc.toml`` lacks."""
    stages = plan_stages(plan.steps)
    needs = plan_needs(plan.steps)
    # The flow target is the last chain step; an inserted check may follow it.
    target = max(index for index, step in enumerate(plan.steps, start=1) if not step.inserted)
    steps = tuple(
        _step_row(
            position,
            step,
            stages[position - 1],
            needs[position - 1],
            final=position == target,
        )
        for position, step in enumerate(plan.steps, start=1)
    )
    problems = [
        PlanProblem(
            kind="flow_violation",
            severity="error" if violation.severity is Severity.ERROR else "warning",
            step=violation.step,
            reason=violation.message(),
            missing=violation.missing_names,
            fixes=violation.fixes,
        )
        for violation in plan.violations
    ]
    entry = plan.enabled_steps[0]
    problems.extend(
        PlanProblem(kind="flow_input", severity="error", step=entry, reason=reason)
        for reason in input_errors
    )
    return StatusView(
        flow=flow, steps=steps, problems=tuple(problems), max_parallel_steps=max_parallel_steps
    )


def view_records(view: StatusView) -> list[Record]:
    """A ``flow_status`` summary, one ``flow_step`` per step, then the problems."""
    records: list[Record] = [
        {
            "record": "flow_status",
            "flow": view.flow,
            "status": view.status,
            "enabled_count": view.enabled_count,
            "step_count": len(view.steps),
            "skip_steps": list(view.skip_steps),
            "insert_steps": list(view.insert_steps),
            "max_parallel_steps": view.max_parallel_steps,
        }
    ]
    records.extend(
        {
            "record": "flow_step",
            "position": step.position,
            "step": step.step,
            "tool": step.tool,
            "enabled": step.enabled,
            "optional": step.optional,
            "target": step.target,
            "requires": list(step.requires),
            "uses": list(step.uses),
            "provides": list(step.provides),
            "stage": step.stage,
            "slot": step.slot,
            "label": step.label,
            "parallel_with": list(step.parallel_with),
            "after": list(step.after),
            "needs": dict(step.needs),
            "check": step.check,
            "inserted": step.inserted,
        }
        for step in view.steps
    )
    for problem in view.problems:
        record: Record = {
            "record": problem.kind,
            "severity": problem.severity,
            "step": problem.step,
        }
        if problem.kind == "flow_violation":
            record["missing"] = list(problem.missing)
            record["fixes"] = list(problem.fixes)
        record["reason"] = problem.reason
        records.append(record)
    return records


def view_from_records(records: Sequence[Mapping[str, object]]) -> StatusView:
    """The view :func:`view_records` reported; raises ``ValueError`` otherwise."""
    if not records or records[0].get("record") != "flow_status":
        raise ValueError("flow status records must start with a flow_status summary")
    steps: list[StepRow] = []
    problems: list[PlanProblem] = []
    for record in records[1:]:
        kind = record.get("record")
        if kind == "flow_step":
            steps.append(
                StepRow(
                    position=record_int(record, "position"),
                    step=record_str(record, "step"),
                    tool=record_str(record, "tool"),
                    enabled=_bool(record, "enabled"),
                    optional=_bool(record, "optional"),
                    target=_bool(record, "target"),
                    requires=record_strings(record, "requires"),
                    uses=record_strings(record, "uses"),
                    provides=record_strings(record, "provides"),
                    stage=_optional_int(record, "stage"),
                    slot=record_str(record, "slot"),
                    label=record_str(record, "label"),
                    parallel_with=record_strings(record, "parallel_with"),
                    after=record_strings(record, "after"),
                    needs=_needs(record, "needs"),
                    check=_bool(record, "check"),
                    inserted=_bool(record, "inserted"),
                )
            )
        elif kind == "flow_violation" or kind == "flow_input":
            problem_kind: ProblemKind = (
                "flow_violation" if kind == "flow_violation" else "flow_input"
            )
            severity = record_str(record, "severity")
            if severity != "error" and severity != "warning":
                raise ValueError(f"unknown problem severity: {severity!r}")
            problems.append(
                PlanProblem(
                    kind=problem_kind,
                    severity=severity,
                    step=record_str(record, "step"),
                    reason=record_str(record, "reason"),
                    missing=record_strings(record, "missing") if kind == "flow_violation" else (),
                    fixes=record_strings(record, "fixes") if kind == "flow_violation" else (),
                )
            )
        else:
            raise ValueError(f"unexpected flow status record: {kind!r}")
    return StatusView(
        flow=record_str(records[0], "flow"),
        steps=tuple(steps),
        problems=tuple(problems),
        max_parallel_steps=record_int(records[0], "max_parallel_steps"),
    )


def _step_row(
    position: int, step: PlannedStep, stage: StepStage, needs: StepNeeds, *, final: bool
) -> StepRow:
    policy = flow_step_policy(step.name)
    provides: set[str] = {str(item) for item in policy.provides}
    if policy.legality is PlacementLegality.LEGALIZED:
        provides.add(DesignState.LEGAL.value)
    return StepRow(
        position=position,
        step=step.name,
        tool=step.tool,
        enabled=step.enabled,
        optional=step.optional,
        target=final,
        requires=tuple(sorted(str(item) for item in policy.requires)),
        uses=tuple(sorted(str(item) for item in policy.uses)),
        provides=tuple(sorted(provides)),
        stage=stage.stage,
        slot=stage.slot,
        label=stage.label,
        parallel_with=stage.parallel_with,
        after=needs.after,
        needs=needs.producers,
        check=policy.category is FlowStepCategory.CHECKER and not provides,
        inserted=step.inserted,
    )


def _field(record: Mapping[str, object], key: str) -> object:
    if key not in record:
        raise ValueError(f"flow status record lacks {key!r}")
    return record[key]


def record_str(record: Mapping[str, object], key: str) -> str:
    """The string field *key*; raises ``ValueError`` when absent or not a string."""
    value = _field(record, key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string, not {value!r}")
    return value


def record_int(record: Mapping[str, object], key: str) -> int:
    """The integer field *key*; raises ``ValueError`` when absent or not an integer."""
    value = _field(record, key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer, not {value!r}")
    return value


def _optional_int(record: Mapping[str, object], key: str) -> int | None:
    return None if _field(record, key) is None else record_int(record, key)


def _bool(record: Mapping[str, object], key: str) -> bool:
    value = _field(record, key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean, not {value!r}")
    return value


def record_strings(record: Mapping[str, object], key: str) -> tuple[str, ...]:
    """The list-of-strings field *key*; raises ``ValueError`` otherwise."""
    value = _field(record, key)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list, not {value!r}")
    items: list[str] = []
    for item in cast("list[object]", value):
        if not isinstance(item, str):
            raise ValueError(f"{key} entries must be strings, not {item!r}")
        items.append(item)
    return tuple(items)


def _needs(record: Mapping[str, object], key: str) -> tuple[tuple[str, str | None], ...]:
    """The capability -> producer mapping field *key*; raises ``ValueError`` otherwise."""
    value = _field(record, key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object, not {value!r}")
    pairs: list[tuple[str, str | None]] = []
    for capability, producer in cast("dict[object, object]", value).items():
        if not isinstance(capability, str):
            raise ValueError(f"{key} capabilities must be strings, not {capability!r}")
        if producer is not None and not isinstance(producer, str):
            raise ValueError(f"{key} producers must be strings or null, not {producer!r}")
        pairs.append((capability, producer))
    return tuple(pairs)
