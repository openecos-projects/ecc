# pyright: strict
"""The ``ecc flow edit`` checkbox: the rich step table, driven by single keys.

The plan is recomputed after every toggle and redrawn with its problems, so a
selection that leaves a step without required design data cannot be saved.
``i`` inserts an LEC after the step under the cursor (``lec@CTS``) and toggling
an inserted row removes it. ``←``/``→`` change ``max_parallel_steps``, which
only the legend depends on. The saved selection is then confirmed before
ecc.toml is written.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from rich.console import Console, RenderableType
from rich.live import Live

from chipcompiler.cli.interactive.terminal import (
    CANCEL,
    DOWN,
    ENTER,
    LEFT,
    RIGHT,
    UP,
    KeyReader,
    next_key,
)
from chipcompiler.cli.project.flow_status_view import StatusView
from chipcompiler.cli.rendering.flow_selection_view import flow_selection_view
from chipcompiler.data import DEFAULT_MAX_PARALLEL_STEPS, StepEnum
from chipcompiler.rtl2gds import inserted_step_name, lec_insert_anchors, resolve_insert_steps

#: The view of the flow without the given (canonical) skipped steps and with
#: the given (canonical) inserted steps.
ViewOf = Callable[[tuple[str, ...], tuple[str, ...]], StatusView]

_TOGGLE = frozenset({" ", "x"})
_INSERT = frozenset({"i"})
_KEYS = "↑/↓ move · space toggle · i insert LEC · ←/→ parallel steps · enter save · q cancel"


@dataclass(frozen=True, slots=True)
class EditedSelection:
    """What the checkbox saved: the skipped and inserted steps and ``max_parallel_steps``."""

    skip_steps: tuple[str, ...]
    insert_steps: tuple[str, ...]
    max_parallel_steps: int


def edit_selection(
    skip_steps: Sequence[str],
    insert_steps: Sequence[str] = (),
    *,
    view_of: ViewOf,
    console: Console,
    read_key: KeyReader,
) -> EditedSelection | None:
    """Toggle and insert steps, and set ``max_parallel_steps``, until saved or
    cancelled (None).

    The value starts as the first view's ``max_parallel_steps``.
    """
    skip = tuple(skip_steps)
    insert = tuple(insert_steps)
    view = view_of(skip, insert)
    started = view.max_parallel_steps
    parallel = started
    cursor = 0
    notice = ""

    def render() -> RenderableType:
        shown = replace(view, max_parallel_steps=parallel)
        footer = [_KEYS, notice] if notice else [_KEYS]
        if not any(step.parallel_with for step in view.steps):
            # No legend states the value, so say it here.
            footer.insert(0, f"max_parallel_steps = {parallel}")
        return flow_selection_view(shown, cursor=cursor, footer="\n".join(footer))

    pending: list[str] = []
    with Live(render(), console=console, auto_refresh=False, transient=True) as live:
        while True:
            try:
                key = next_key(pending, read_key)
            except (KeyboardInterrupt, EOFError):
                return None
            notice = ""
            if key in UP:
                cursor = (cursor - 1) % len(view.steps)
            elif key in DOWN:
                cursor = (cursor + 1) % len(view.steps)
            elif key in _TOGGLE:
                row = view.steps[cursor]
                if row.inserted and row.step not in insert:
                    notice = f"{row.step} is part of the preset"
                elif row.inserted:
                    insert = tuple(name for name in insert if name != row.step)
                    view = view_of(skip, insert)
                    cursor = min(cursor, len(view.steps) - 1)
                elif row.target:
                    notice = f"{row.step} ends the flow and stays enabled"
                else:
                    skip = _toggled(skip, row.step, [step.step for step in view.steps])
                    view = view_of(skip, insert)
            elif key in _INSERT:
                row = view.steps[cursor]
                if row.step not in lec_insert_anchors():
                    notice = (
                        "an LEC can be inserted after a design-building step from "
                        "Synthesis to route"
                    )
                elif (name := inserted_step_name(StepEnum.LEC.value, row.step)) in insert:
                    notice = f"{name} is already inserted"
                else:
                    insert = resolve_insert_steps({"insert_steps": [*insert, name]})
                    view = view_of(skip, insert)
            elif key in LEFT:
                parallel = max(parallel - 1, 1)
            elif key in RIGHT:
                # A larger value than any stage (or the default) could never matter.
                bound = max(DEFAULT_MAX_PARALLEL_STEPS, _largest_stage(view), started)
                parallel = parallel + 1 if parallel < bound else parallel
            elif key in ENTER:
                if not view.blocks_saving:
                    return EditedSelection(skip, insert, parallel)
                notice = "resolve the errors before saving"
            elif key in CANCEL:
                return None
            live.update(render(), refresh=True)


def _largest_stage(view: StatusView) -> int:
    """The most steps one stage of *view* can run at once."""
    return max((len(step.parallel_with) + 1 for step in view.steps), default=1)


def _toggled(skip: tuple[str, ...], name: str, order: Sequence[str]) -> tuple[str, ...]:
    """*skip* with *name* flipped, in chain order."""
    selected = set(skip) ^ {name}
    return tuple(step for step in order if step in selected)
