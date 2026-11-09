"""The ``ecc flow edit`` checkbox, driven by scripted keys on a recording console."""

import io

import pytest
from rich.console import Console
from rich.text import Text

from chipcompiler.cli.interactive.flow_edit import confirm_write, edit_selection, split_keys
from chipcompiler.cli.project.flow_plan_view import PlanView, plan_view
from chipcompiler.data import DEFAULT_SKIP_STEPS
from chipcompiler.data.flow_plan import plan_flow, preset_chain
from chipcompiler.rtl2gds import rtl2gds_step_names

_DOWN = "\x1b[B"
_UP = "\x1b[A"
_SPACE = " "
_ENTER = "\r"


@pytest.fixture(autouse=True)
def _redrawing_terminal(monkeypatch):
    # rich draws nothing live on TERM=dumb/unknown; the console here stands
    # for a terminal that redraws, whatever terminal runs the tests.
    monkeypatch.setenv("TERM", "xterm-256color")


def _view_of(skip: tuple[str, ...]) -> PlanView:
    return plan_view(plan_flow(preset_chain("rtl2gds"), skip_steps=skip), flow="rtl2gds")


def _screen():
    screen = io.StringIO()
    return screen, Console(file=screen, force_terminal=True, width=140)


def _edit(keys, skip=DEFAULT_SKIP_STEPS):
    screen, console = _screen()
    scripted = iter(keys)
    result = edit_selection(
        skip, view_of=_view_of, console=console, read_key=lambda: next(scripted)
    )
    return result, screen.getvalue()


def _moves_to(step: str) -> list[str]:
    return [_DOWN] * rtl2gds_step_names().index(step)


def test_space_toggles_the_step_under_the_cursor_and_enter_saves():
    result, output = _edit([*_moves_to("CTS"), _SPACE, _ENTER])

    assert result == (*DEFAULT_SKIP_STEPS, "CTS")
    assert "route runs with degraded results without clock_tree; enable CTS" in output


def test_the_flow_target_stays_enabled():
    result, output = _edit([_UP, _SPACE, _ENTER])

    assert result == DEFAULT_SKIP_STEPS
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

    assert result == ("diff_opt",)


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
