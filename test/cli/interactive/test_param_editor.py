"""The ``ecc param edit`` editor, driven by scripted keys on a recording console."""

import io

import pytest
from rich.console import Console

from chipcompiler.cli.interactive.param_edit import ParamChanges, ParamRow, edit_parameters

_DOWN = "\x1b[B"
_ENTER = "\r"
_ESC = "\x1b"
_CLEAR = "\x15"

_ROWS = [
    ParamRow("design.frequency_mhz", "design", "100.0", "100.0", overridden=False, kind="float"),
    ParamRow("place.target_density", "place", "0.7", "0.6", overridden=True, kind="float"),
    ParamRow("place.routability_opt", "place", "false", "false", overridden=False, kind="bool"),
]


@pytest.fixture(autouse=True)
def _redrawing_terminal(monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")


def _check(param, text):
    if param == "place.routability_opt":
        return None if text in {"true", "false"} else f"expected bool for {param}, got '{text}'"
    try:
        float(text)
    except ValueError:
        return f"expected float for {param}, got '{text}'"
    return None


def _edit(keys, rows=_ROWS):
    screen = io.StringIO()
    console = Console(file=screen, force_terminal=True, width=120, height=40)
    scripted = iter(keys)
    changes = edit_parameters(
        rows, title="Parameters", check=_check, console=console, read_key=lambda: next(scripted)
    )
    return changes, screen.getvalue()


def test_an_edited_value_is_saved():
    # Open the place group, edit its first value, save.
    keys = [_DOWN, _ENTER, _ENTER, _CLEAR, "0.8", _ENTER, "s"]

    assert _edit(keys)[0] == ParamChanges(sets=(("place.target_density", "0.8"),), unsets=())


def test_a_value_that_does_not_parse_is_refused_until_corrected():
    keys = [_ENTER, _ENTER, _CLEAR, "fast", _ENTER, _CLEAR, "250", _ENTER, "s"]

    changes, screen = _edit(keys)

    assert "expected float for design.frequency_mhz, got 'fast'" in screen
    assert changes == ParamChanges(sets=(("design.frequency_mhz", "250"),), unsets=())


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        # An override is reset to its base value.
        ([_DOWN, _ENTER, "u", "s"], ParamChanges(sets=(), unsets=("place.target_density",))),
        # Resetting a pending edit drops it; typing the current value back too.
        ([_DOWN, _ENTER, _DOWN, _ENTER, _CLEAR, "true", _ENTER, "u", "s", "q"], None),
        ([_ENTER, _ENTER, _CLEAR, "5", _ENTER, _ENTER, _CLEAR, "100.0", _ENTER, "s", "q"], None),
    ],
)
def test_reset_removes_an_override_or_a_pending_edit(keys, expected):
    changes, screen = _edit(keys)

    assert changes == expected
    if expected is None:
        assert "no changes to save" in screen


def test_escape_leaves_a_value_unchanged():
    keys = [_ENTER, _ENTER, _CLEAR, "5", _ESC, "s", "q"]

    changes, screen = _edit(keys)

    assert changes is None
    assert "no changes to save" in screen


def test_pending_changes_are_discarded_only_on_a_second_cancel():
    keys = [_ENTER, _ENTER, _CLEAR, "5", _ENTER, "q", "q"]

    changes, screen = _edit(keys)

    assert changes is None
    assert "1 unsaved change(s): press q again to discard" in screen


def test_one_group_opens_its_values_and_the_filter_narrows_them():
    place = [row for row in _ROWS if row.group == "place"]
    # The filter leaves place.routability_opt as the only row: enter edits it.
    keys = ["/", "rout", _ENTER, _ENTER, _CLEAR, "true", _ENTER, "s"]

    changes, screen = _edit(keys, rows=place)

    assert changes == ParamChanges(sets=(("place.routability_opt", "true"),), unsets=())
    assert "Group" not in screen


def test_escape_goes_back_from_a_group_to_the_groups():
    # esc returns to the groups, so the second enter opens design again.
    keys = [_DOWN, _ENTER, _ESC, "\x1b[A", _ENTER, _ENTER, _CLEAR, "200", _ENTER, "s"]

    assert _edit(keys)[0] == ParamChanges(sets=(("design.frequency_mhz", "200"),), unsets=())
