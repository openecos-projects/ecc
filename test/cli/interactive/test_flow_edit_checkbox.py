"""The ``ecc flow edit`` checkbox, driven by scripted keys on a recording console."""

import io

import pytest
from rich.console import Console
from rich.text import Text

from chipcompiler.cli.interactive.flow_edit import (
    EditedSelection,
    confirm_write,
    edit_selection,
    split_keys,
)
from chipcompiler.cli.project.flow_plan_view import PlanView, plan_view
from chipcompiler.data import DEFAULT_SKIP_STEPS
from chipcompiler.data.flow_plan import plan_flow, preset_chain
from chipcompiler.rtl2gds import rtl2gds_step_names

_DOWN = "\x1b[B"
_UP = "\x1b[A"
_LEFT = "\x1b[D"
_RIGHT = "\x1b[C"
_SPACE = " "
_ENTER = "\r"


@pytest.fixture(autouse=True)
def _redrawing_terminal(monkeypatch):
    # rich draws nothing live on TERM=dumb/unknown; the console here stands
    # for a terminal that redraws, whatever terminal runs the tests.
    monkeypatch.setenv("TERM", "xterm-256color")


def _view_of_project(max_parallel_steps: int, **bounds):
    def view_of(skip: tuple[str, ...]) -> PlanView:
        plan = plan_flow(preset_chain("rtl2gds"), skip_steps=skip, **bounds)
        return plan_view(plan, flow="rtl2gds", max_parallel_steps=max_parallel_steps)

    return view_of


_view_of = _view_of_project(4)


def _screen():
    screen = io.StringIO()
    # Tall enough that live redraws are never cropped to the terminal height.
    return screen, Console(file=screen, force_terminal=True, width=140, height=60)


def _edit(keys, skip=DEFAULT_SKIP_STEPS, view_of=_view_of):
    screen, console = _screen()
    scripted = iter(keys)
    result = edit_selection(skip, view_of=view_of, console=console, read_key=lambda: next(scripted))
    return result, screen.getvalue()


def _moves_to(step: str) -> list[str]:
    return [_DOWN] * rtl2gds_step_names().index(step)


def test_space_toggles_the_step_under_the_cursor_and_enter_saves():
    result, output = _edit([*_moves_to("CTS"), _SPACE, _ENTER])

    assert result == EditedSelection((*DEFAULT_SKIP_STEPS, "CTS"), 4)
    assert "route runs with degraded results without clock_tree; enable CTS" in output


def test_the_flow_target_stays_enabled():
    result, output = _edit([_UP, _SPACE, _ENTER])

    assert result == EditedSelection(DEFAULT_SKIP_STEPS, 4)
    assert "Harden ends the flow and stays enabled" in output


def test_a_selection_missing_required_data_cannot_be_saved():
    keys = [*_moves_to("legalization"), _SPACE, _DOWN, _SPACE, _ENTER, "q"]

    result, output = _edit(keys)

    assert result is None
    assert "route requires legal; enable Timing optimization or legalization" in output
    assert "resolve the errors before saving" in output


@pytest.mark.parametrize("keys", [["q"], ["\x1b"]])
def test_cancel_keys_leave_the_selection_unsaved(keys):
    assert _edit(keys)[0] is None


@pytest.mark.parametrize(
    ("keys", "value"),
    [
        ([_LEFT], 3),
        (["\x1bOD", "\x1bOD"], 2),
        (["-", "-", "-"], 1),
        ([_RIGHT], 5),
        (["\x1bOC"], 5),
        (["+"], 5),
        # Windows scan codes: \xe0 K is left, \xe0 M is right.
        (["\xe0", "K", "\xe0", "K"], 2),
        (["\xe0", "M"], 5),
        # Anywhere in the list, with toggles in between.
        ([_DOWN, _LEFT, _DOWN, _RIGHT, _RIGHT], 5),
    ],
)
def test_left_and_right_change_the_value_wherever_the_cursor_is(keys, value):
    result, _output = _edit([*keys, _ENTER])

    assert result == EditedSelection(DEFAULT_SKIP_STEPS, value)


def test_the_value_stays_within_one_and_the_largest_stage():
    # The largest stage of the default flow is 13a..13e: five steps.
    lowered, _ = _edit([_LEFT] * 6 + [_ENTER])
    raised, _ = _edit([_RIGHT] * 6 + [_ENTER])

    assert (lowered, raised) == (
        EditedSelection(DEFAULT_SKIP_STEPS, 1),
        EditedSelection(DEFAULT_SKIP_STEPS, 5),
    )


def test_a_value_above_the_default_and_every_stage_is_kept_and_can_be_lowered():
    view_of = _view_of_project(8)

    kept, _ = _edit([_RIGHT, _ENTER], view_of=view_of)
    lowered, _ = _edit([_LEFT, _ENTER], view_of=view_of)

    assert (kept, lowered) == (
        EditedSelection(DEFAULT_SKIP_STEPS, 8),
        EditedSelection(DEFAULT_SKIP_STEPS, 7),
    )


def test_the_default_bounds_the_value_when_no_stage_is_parallel():
    view_of = _view_of_project(4, start="Synthesis", end="preFloorplan")

    result, _output = _edit([_RIGHT, _ENTER], view_of=view_of)

    assert result == EditedSelection(DEFAULT_SKIP_STEPS, 4)


def test_toggles_alone_keep_the_value_the_editor_started_with():
    result, _output = _edit([_DOWN, _SPACE, _ENTER], view_of=_view_of_project(2))

    assert result == EditedSelection(("diff_opt",), 2)


def test_the_legend_and_key_hint_follow_the_value():
    _result, output = _edit([_LEFT, _LEFT, _LEFT, _ENTER])

    assert "↑/↓ move · space toggle · ←/→ parallel steps · enter save · q cancel" in output
    assert "┐…┘ same number = can run in parallel, up to 4 at once" in output
    assert "┐…┘ same number = can run in parallel, up to 2 at once" in output
    assert "┐…┘ same number = independent steps; run one at a time (max_parallel_steps = 1)" in (
        output
    )


def test_the_value_is_shown_when_no_stage_has_parallel_steps():
    view_of = _view_of_project(4, start="Synthesis", end="preFloorplan")

    result, output = _edit([_LEFT, _ENTER], view_of=view_of)

    assert result == EditedSelection(DEFAULT_SKIP_STEPS, 3)
    assert "max_parallel_steps = 4" in output
    assert "max_parallel_steps = 3" in output
    assert "┐…┘" not in output


def test_interrupt_cancels():
    def interrupted() -> str:
        raise KeyboardInterrupt

    console = Console(file=io.StringIO(), force_terminal=True)
    assert (
        edit_selection(DEFAULT_SKIP_STEPS, view_of=_view_of, console=console, read_key=interrupted)
        is None
    )


@pytest.mark.parametrize(
    ("keys", "answer"),
    [
        (["y"], True),
        (["n"], False),
        ([_ENTER], False),
        (["\x1b"], False),
        # Keys that answer nothing are ignored until one does.
        ([f"{_DOWN}x", "Y"], True),
    ],
)
def test_only_y_confirms_the_write(keys, answer):
    screen, console = _screen()
    scripted = iter(keys)

    confirmed = confirm_write(
        Text("Write [flow] to ecc.toml?"), console=console, read_key=lambda: next(scripted)
    )

    assert confirmed is answer
    assert "Write [flow] to ecc.toml?" in screen.getvalue()


def test_interrupt_declines_the_write():
    def interrupted() -> str:
        raise KeyboardInterrupt

    assert confirm_write(Text(""), console=_screen()[1], read_key=interrupted) is False


def test_windows_arrow_keys_move_the_cursor():
    # \xe0 + P is the Windows down arrow: enable lec (row 2), then save.
    result, _output = _edit(["\xe0", "P", _SPACE, _ENTER])

    assert result == EditedSelection(("diff_opt",), 4)


@pytest.mark.parametrize(
    ("chunk", "keys"),
    [
        ("\x1b[B\x1b[B \r", ["\x1b[B", "\x1b[B", " ", "\r"]),
        ("\x1bOAq", ["\x1bOA", "q"]),
        ("\x1b", ["\x1b"]),
        ("\xe0P", ["\x1b[B"]),
    ],
)
def test_one_terminal_read_splits_into_its_keys(chunk, keys):
    assert split_keys(chunk) == keys
