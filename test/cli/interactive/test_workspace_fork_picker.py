"""The ``ecc workspace fork`` picker, driven by scripted keys on a recording console."""

import io

import pytest
from rich.console import Console

from chipcompiler.cli.interactive.workspace_fork import (
    ForkChoice,
    SourceRow,
    StepRow,
    choose_fork,
)

_UP = "\x1b[A"
_DOWN = "\x1b[B"
_ENTER = "\r"
_ESC = "\x1b"
_CLEAR = "\x15"

_SOURCES = [
    SourceRow("old", "created", 0, 3, blocked="it has no Engineering Snapshot"),
    SourceRow("base", "success", 3, 3),
]
_STEPS = [StepRow("Synthesis", "Success"), StepRow("place", "Success"), StepRow("route", "Success")]


@pytest.fixture(autouse=True)
def _redrawing_terminal(monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")


def _choose(keys, *, source=None, target=None, taken=()):
    screen = io.StringIO()
    console = Console(file=screen, force_terminal=True, width=120, height=40)
    scripted = iter(keys)
    choice = choose_fork(
        _SOURCES,
        lambda workspace_id: _STEPS if workspace_id == "base" else [],
        source=source,
        target=target,
        suggest_name=lambda workspace_id: f"{workspace_id}-1",
        check_name=lambda name: f"{name} already exists" if name in taken else None,
        console=console,
        read_key=lambda: next(scripted),
    )
    return choice, screen.getvalue()


def test_a_fork_is_chosen_screen_by_screen():
    # Enter on the blocked source is refused; base reruns from place under the suggested name.
    keys = [_ENTER, _DOWN, _ENTER, _DOWN, _ENTER, _ENTER, "y"]

    choice, screen = _choose(keys)

    assert "old cannot be forked: it has no Engineering Snapshot" in screen
    assert choice == ForkChoice("base", "place", None, "base-1", edit_parameters=False)
    assert choice is not None
    assert choice.rerun_steps(_STEPS) == ["place", "route"]


def test_the_last_step_bounds_the_fork_and_its_parameters():
    keys = [_DOWN, "t", _UP, _ENTER, _CLEAR, "trial", _ENTER, "e"]

    choice, _screen = _choose(keys, source="base")

    assert choice == ForkChoice("base", "place", "place", "trial", edit_parameters=True)
    assert choice is not None
    assert choice.rerun_steps(_STEPS) == ["place"]


def test_a_name_in_use_is_refused():
    keys = [_ENTER, _CLEAR, "base", _ENTER, _CLEAR, "base-2", _ENTER, "y"]

    choice, screen = _choose(keys, source="base", taken={"base"})

    assert "base already exists" in screen
    assert choice == ForkChoice("base", "Synthesis", None, "base-2", edit_parameters=False)


def test_escape_steps_back_and_a_given_target_skips_the_name():
    # From the summary back to the steps, then from route on.
    keys = [_ENTER, _ESC, _DOWN, _DOWN, _ENTER, "y"]

    choice, _screen = _choose(keys, source="base", target="given")

    assert choice == ForkChoice("base", "route", None, "given", edit_parameters=False)


@pytest.mark.parametrize("keys", [["q"], [_ESC], [_ENTER, _ENTER, "n"], [_ENTER, _ENTER, "q"]])
def test_cancelling_chooses_nothing(keys):
    assert _choose(keys, source="base")[0] is None
