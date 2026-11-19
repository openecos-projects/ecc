"""``plan_stages``: which enabled steps the engine may run in parallel.

The enabled steps are grouped with the engine's own analysis-wave rule
(:func:`~chipcompiler.data.workspace.flow_policy.analysis_wave_end`), applied to
records built like the ledger's, so the stages shown are the ones a fresh run of
the selection gets. A disabled step never enters the ledger and has no stage:
toggling a step renumbers the stages after it, and ``position`` stays the
stable index in the chain.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from string import ascii_lowercase

from chipcompiler.data.flow_plan import PlannedStep
from chipcompiler.data.types import flow_step_policy
from chipcompiler.data.workspace.flow_policy import analysis_wave_end


@dataclass(frozen=True, slots=True)
class StepStage:
    #: 1-based number of the wave among the enabled steps; ``None`` when disabled.
    stage: int | None
    #: ``a``, ``b``, ... in chain order within a parallel stage; empty when alone.
    slot: str
    #: The other steps of the stage.
    parallel_with: tuple[str, ...]

    @property
    def label(self) -> str:
        return "" if self.stage is None else f"{self.stage}{self.slot}"


_DISABLED = StepStage(stage=None, slot="", parallel_with=())


def plan_stages(steps: Sequence[PlannedStep]) -> tuple[StepStage, ...]:
    """The stage of every planned step, in step order; a disabled step has none."""
    enabled = [step for step in steps if step.enabled]
    records = [
        {
            "name": step.name,
            "tool": step.tool,
            "category": flow_step_policy(step.name).category.value,
        }
        for step in enabled
    ]
    waves: list[StepStage] = []
    number = 0
    start = 0
    while start < len(enabled):
        end = analysis_wave_end(records, start)
        members = [step.name for step in enabled[start:end]]
        number += 1
        waves.extend(
            StepStage(
                stage=number,
                slot=ascii_lowercase[offset] if len(members) > 1 else "",
                parallel_with=tuple(other for other in members if other != name),
            )
            for offset, name in enumerate(members)
        )
        start = end
    stages = iter(waves)
    return tuple(next(stages) if step.enabled else _DISABLED for step in steps)
