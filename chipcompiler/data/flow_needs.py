"""``plan_needs``: which enabled step supplies the design data each step needs.

For every capability a step requires or uses, the producer is the nearest
earlier enabled step that provides it (:func:`step_provides`); a capability
nothing enabled provides has no producer. Disabled steps are described too
(against the enabled steps before them) so the table stays complete while a
selection is toggled.

A step's ``after`` lists those producers, nearest first, minus any producer that
every capability the step takes from it is also taken from by another producer
of the step (that producer's own capability map names it). So ``sta`` does not
follow ``filler`` (``RCX`` already does) but still follows ``CTS``, whose clock
tree nothing else it follows hands on. An inserted step (``lec@CTS``) also
follows the step it is inserted after, whose netlist it checks, first.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from chipcompiler.data.flow_check import step_provides
from chipcompiler.data.flow_plan import PlannedStep
from chipcompiler.data.types import DesignData, flow_step_policy


@dataclass(frozen=True, slots=True)
class StepNeeds:
    #: Capability -> its producer step (``None`` when no enabled step provides it),
    #: for every required and used capability, sorted by capability.
    producers: tuple[tuple[str, str | None], ...]
    #: The distinct producers, nearest first, without a producer P when every
    #: capability this step takes from P is also taken from P by another producer
    #: of this step (that producer's own capability map names P for it).
    after: tuple[str, ...]


def plan_needs(steps: Sequence[PlannedStep]) -> tuple[StepNeeds, ...]:
    """The needs of every planned step, in step order."""
    from chipcompiler.rtl2gds import parse_inserted_step

    policies = [flow_step_policy(step.name) for step in steps]

    def producer_index(index: int, item: DesignData) -> int | None:
        return next(
            (
                earlier
                for earlier in range(index - 1, -1, -1)
                if steps[earlier].enabled and step_provides(steps[earlier].name, item)
            ),
            None,
        )

    by_capability = [
        {str(item): producer_index(index, item) for item in sorted(policy.requires | policy.uses)}
        for index, policy in enumerate(policies)
    ]

    def after(index: int) -> tuple[str, ...]:
        found = by_capability[index]
        producers = sorted({value for value in found.values() if value is not None}, reverse=True)

        def covered(producer: int) -> bool:
            # Every capability taken from *producer* is also relayed by another producer.
            return all(
                any(
                    by_capability[other].get(capability) == producer
                    for other in producers
                    if other != producer
                )
                for capability, source in found.items()
                if source == producer
            )

        names = tuple(steps[producer].name for producer in producers if not covered(producer))
        checked = parse_inserted_step(steps[index].name) if steps[index].inserted else None
        if checked is None:
            return names
        return (checked[1], *(name for name in names if name != checked[1]))

    return tuple(
        StepNeeds(
            producers=tuple(
                (capability, None if producer is None else steps[producer].name)
                for capability, producer in sorted(by_capability[index].items())
            ),
            after=after(index),
        )
        for index in range(len(steps))
    )
