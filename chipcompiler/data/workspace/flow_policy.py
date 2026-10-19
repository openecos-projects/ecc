"""One implementation of the flow ledger's input-source rule.

Two readings of a ledger are owned here: the effective category of a record
(top level, then ``info.category``, then PNR) and which step feeds a step's
inputs. The execution engine, the read-only projections, the signoff analysis
and the post-route LEC gate all call this module instead of re-deriving the
rule.

Input chaining follows the physical chain: a step consumes the output of the
previous non-LEC, non-advisory step, the step named by its explicit
``input_step``, or the source declared by its policy. Physical signoff steps
read ``filler`` directly, and the parallel checker batch immediately after
``filler`` also reads that anchor.
"""

from chipcompiler.data.types import (
    ADVISORY_FLOW_STEPS,
    LEC_STEP_TOOLS,
    FlowInputSource,
    FlowStepCategory,
    StepEnum,
    flow_step_policy,
)


class FlowInputStepError(Exception):
    """A ledger step names an input that is missing or not created yet."""


def step_name(record: dict) -> str:
    return str(record.get("name") or "")


def step_tool(record: dict) -> str:
    return str(record.get("tool") or "")


def explicit_input_step(record: dict) -> str | None:
    """The step explicitly declared as this step's input, if any."""
    return record.get("input_step") or (record.get("info") or {}).get("input_step")


def _declared_category(record: dict) -> FlowStepCategory | None:
    value = record.get("category") or (record.get("info") or {}).get("category")
    if not value:
        return None
    try:
        return FlowStepCategory(str(value).upper())
    except ValueError:
        return None


def ledger_category(record: dict) -> FlowStepCategory:
    """The category the ledger declares: top level, then ``info.category``.

    A ledger without either predates the category field; execution treats its
    steps as PNR so the historical chaining is preserved. An unregistered step
    name raises before any category is honored.
    """
    flow_step_policy(step_name(record))
    return _declared_category(record) or FlowStepCategory.PNR


def flow_category(record: dict) -> FlowStepCategory:
    """The category for classification: declared, else the registered policy.

    An unregistered step name raises rather than silently reading as PNR,
    even when the record carries an explicit category.
    """
    policy = flow_step_policy(step_name(record))
    declared = _declared_category(record)
    return declared if declared is not None else policy.category


def is_checker_batch_step(record: dict) -> bool:
    """Whether the step belongs to the parallel checker batch.

    Only steps whose policy declares the batch input source run concurrently;
    the batch is anchored at ``filler``. A ledger without categories keeps the
    historical all-PNR chaining.
    """
    try:
        category = ledger_category(record)
        policy = flow_step_policy(step_name(record))
    except ValueError:
        # Dispatch treats an unregistered step as non-batchable; the input
        # chain resolver is where an unknown step fails loudly.
        return False
    if category != FlowStepCategory.CHECKER:
        return False
    return policy.input_source is FlowInputSource.CHECKER_BATCH


def is_lec_record(record: dict) -> bool:
    return step_tool(record) in LEC_STEP_TOOLS


def is_advisory_record(record: dict) -> bool:
    return step_name(record) in ADVISORY_FLOW_STEPS


def checker_batch_anchor(records: list[dict], index: int) -> str | None:
    """The step a parallel checker batch reads: the step before the batch.

    A batch is a maximal run of CHECKER steps immediately after ``filler``
    (the engine starts the batch there). Checker steps elsewhere are ordinary
    steps and chain from their predecessor.
    """
    if not is_checker_batch_step(records[index]):
        return None
    run_start = index
    while run_start > 0 and is_checker_batch_step(records[run_start - 1]):
        run_start -= 1
    if run_start == 0:
        return None
    anchor = records[run_start - 1]
    if step_name(anchor) != StepEnum.FILLER.value:
        return None
    return step_name(anchor)


def filler_anchor(records: list[dict], index: int) -> str | None:
    """The nearest ``filler`` before *index*, if the ledger has one."""
    for previous in reversed(records[:index]):
        if step_name(previous) == StepEnum.FILLER.value:
            return StepEnum.FILLER.value
    return None


class FlowInputResolver:
    """Resolve ledger step inputs in order, one resolver per walk.

    Call :meth:`record` after building each step; the resolver keeps the
    created steps by name so later steps can reference them.
    """

    def __init__(self, records: list[dict] | None):
        self._records = [record for record in records or [] if isinstance(record, dict)]
        self._positions: dict[str, list[int]] = {}
        for index, record in enumerate(self._records):
            self._positions.setdefault(step_name(record), []).append(index)
        self._created: dict[str, object] = {}

    def record(self, step) -> None:
        self._created[step.name] = step

    def created_step(self, name: str):
        """A step created earlier in this walk, or None when it is not available."""
        return self._created.get(name)

    def _resolve(self, index: int, *, require_created: bool) -> tuple[str | None, bool]:
        record = self._records[index]
        try:
            flow_step_policy(step_name(record))
        except ValueError as error:
            raise FlowInputStepError(str(error)) from None
        explicit = explicit_input_step(record)
        if explicit is not None:
            positions = self._positions.get(explicit, [])
            if not positions or min(positions) >= index:
                where = "missing from" if not positions else "defined after this step in"
                raise FlowInputStepError(
                    f"{step_name(record) or 'step'}: input step {explicit!r} "
                    f"is {where} the flow ledger"
                )
            if require_created and explicit not in self._created:
                raise FlowInputStepError(
                    f"{step_name(record) or 'step'}: input step {explicit!r} was not created"
                )
            return explicit, True

        policy = flow_step_policy(step_name(record))
        if policy.input_source in (FlowInputSource.FILLER, FlowInputSource.CHECKER_BATCH):
            anchor = filler_anchor(self._records, index)
            if anchor is not None and (not require_created or anchor in self._created):
                return anchor, False

        anchor = checker_batch_anchor(self._records, index)
        if anchor is not None and (not require_created or anchor in self._created):
            return anchor, False

        for previous in reversed(self._records[:index]):
            if is_lec_record(previous) or is_advisory_record(previous):
                continue
            name = step_name(previous)
            if require_created and name not in self._created:
                continue
            return name or None, False
        return None, False

    def input_step_name(self, index: int) -> str | None:
        """The input step's ledger name, or None when the step reads the origin."""
        name, _explicit = self._resolve(index, require_created=False)
        return name

    def input_source(self, index: int):
        """The created step whose outputs feed step *index*, or None for origin.

        Raises :class:`FlowInputStepError` when an explicit ``input_step`` is
        missing, defined later in the ledger, or was not created.
        """
        name, _explicit = self._resolve(index, require_created=True)
        return None if name is None else self._created[name]
