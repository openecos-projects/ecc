"""``ecc param edit``: parameters edited in the terminal are applied as one batch."""

import pytest

from chipcompiler.cli import main as cli_main

_ENTER = "\r"
_CLEAR = "\x15"
#: Open the first group (design), edit its first value (frequency_mhz), save.
_SET_FREQUENCY = [_ENTER, _ENTER, _CLEAR, "250", _ENTER, "s"]


def test_confirmed_edits_are_applied(ready_project, scripted_terminal, capsys):
    scripted_terminal([*_SET_FREQUENCY, "y"])

    rc = cli_main.run(["param", "edit", "--project", str(ready_project)])

    assert rc == 0, capsys.readouterr().out
    assert "frequency_mhz = 250.0" in (ready_project / "ecc.toml").read_text(encoding="utf-8")


@pytest.mark.parametrize("keys", [[*_SET_FREQUENCY, "n"], ["q"]])
def test_declined_or_cancelled_edits_change_nothing(ready_project, scripted_terminal, keys):
    before = (ready_project / "ecc.toml").read_bytes()
    scripted_terminal(keys)

    assert cli_main.run(["param", "edit", "--project", str(ready_project)]) == 0
    assert (ready_project / "ecc.toml").read_bytes() == before


def test_the_editor_needs_a_terminal(ready_project, capsys):
    rc = cli_main.run(["param", "edit", "--project", str(ready_project)])

    assert rc == 1
    assert "param_edit_requires_terminal" in capsys.readouterr().out
