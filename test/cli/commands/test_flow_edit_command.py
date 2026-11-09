"""`ecc flow edit`: the chosen steps are written back to ecc.toml [flow]."""

import json
import os
import tomllib
from contextlib import contextmanager

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.command_handlers import flow_selection as flow_selection_handlers
from chipcompiler.data import DEFAULT_SKIP_STEPS
from chipcompiler.data.workspace import build_dynamic_flow_data


def _toml(project_dir):
    with open(os.path.join(project_dir, "ecc.toml"), "rb") as f:
        return tomllib.load(f)


def _edit(capsys, project_dir, *args):
    rc = cli_main.run(["flow", "edit", "--project", project_dir, "--json", *args])
    return rc, json.loads(capsys.readouterr().out)


def test_toggles_write_every_flow_key_explicitly(capsys, create_cli_project):
    project_dir = create_cli_project()
    before = _toml(project_dir)

    rc, records = _edit(capsys, project_dir, "--disable", "CTS", "--enable", "diff_opt", "--yes")

    assert rc == 0
    assert records[0] == {
        "record": "flow_edit",
        "status": "written",
        "path": os.path.join(project_dir, "ecc.toml"),
        "preset": "rtl2gds",
        "lec_engine": "kepler_formal",
        "skip_steps": ["lec", "CTS"],
        "enabled": ["diff_opt"],
        "disabled": ["CTS"],
    }
    assert [
        record["step"] for record in records[1:] if record["warning"] == "flow_step_degraded"
    ] == [
        "route",
        "sta",
        "powerAnalysis",
        "Harden",
    ]
    after = _toml(project_dir)
    assert after["flow"] == {
        "preset": "rtl2gds",
        "lec_engine": "kepler_formal",
        "skip_steps": ["lec", "CTS"],
    }
    assert {key: value for key, value in after.items() if key != "flow"} == {
        key: value for key, value in before.items() if key != "flow"
    }


def test_selection_missing_required_data_is_not_written(capsys, create_cli_project):
    project_dir = create_cli_project()
    with open(os.path.join(project_dir, "ecc.toml")) as f:
        before = f.read()

    rc, records = _edit(capsys, project_dir, "--disable", "legalization", "--disable", "TimingOpt")

    assert rc == 1
    assert records == [
        {
            "kind": "error",
            "error": "flow_selection_invalid",
            "step": "route",
            "missing": ["legal"],
            "fixes": ["Timing optimization", "legalization"],
            "reason": "route requires legal; enable Timing optimization or legalization",
        }
    ]
    with open(os.path.join(project_dir, "ecc.toml")) as f:
        assert f.read() == before


def test_a_project_without_a_preset_is_not_edited(capsys, create_cli_project):
    project_dir = create_cli_project()
    toml_path = os.path.join(project_dir, "ecc.toml")
    with open(toml_path) as f:
        before = f.read().replace('preset = "rtl2gds"\n', "")
    with open(toml_path, "w") as f:
        f.write(before)

    rc, records = _edit(capsys, project_dir, "--disable", "CTS", "--yes")

    assert rc == 1
    assert records == [
        {
            "kind": "error",
            "error": "flow_target_missing",
            "reason": "ecc.toml declares no [flow] preset and ecc flow edit edits a preset's "
            "steps; set [flow] preset first",
        }
    ]
    with open(toml_path) as f:
        assert f.read() == before


def test_checkbox_needs_a_terminal(capsys, create_cli_project):
    rc, records = _edit(capsys, create_cli_project())

    assert rc == 1
    assert records[0]["error"] == "flow_edit_requires_terminal"


def test_toggles_without_a_terminal_need_yes(capsys, create_cli_project):
    project_dir = create_cli_project()
    with open(os.path.join(project_dir, "ecc.toml")) as f:
        before = f.read()

    rc, records = _edit(capsys, project_dir, "--disable", "CTS")

    assert rc == 1
    assert [record["error"] for record in records] == ["flow_edit_requires_confirmation"]
    with open(os.path.join(project_dir, "ecc.toml")) as f:
        assert f.read() == before


def test_a_dumb_terminal_cannot_draw_the_checkbox(capsys, monkeypatch, create_cli_project):
    project_dir = create_cli_project()
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)

    rc = cli_main.run(["flow", "edit", "--project", project_dir])

    assert rc == 1
    assert "flow_edit_requires_terminal" in capsys.readouterr().out


def _scripted_terminal(monkeypatch, keys):
    """A terminal session that types *keys*, one read each."""
    scripted = iter(keys)

    @contextmanager
    def scripted_keys():
        yield lambda: next(scripted)

    monkeypatch.setattr(flow_selection_handlers, "_interactive", lambda _ctx: True)
    monkeypatch.setattr("chipcompiler.cli.interactive.flow_edit.terminal_keys", scripted_keys)


@pytest.mark.parametrize(
    ("args", "keys"),
    [
        # One read may hold several keys: enable lec (row 2), save, confirm.
        ([], ["\x1b[B ", "\r", "y"]),
        (["--enable", "lec"], ["y"]),
        (["--yes"], ["\x1b[B ", "\r"]),
    ],
)
def test_terminal_selection_is_written_once_confirmed(
    capsys, monkeypatch, create_cli_project, args, keys
):
    project_dir = create_cli_project()
    _scripted_terminal(monkeypatch, keys)

    rc = cli_main.run(["flow", "edit", "--project", project_dir, *args])

    assert rc == 0
    assert "✔ wrote [flow] to" in capsys.readouterr().out
    assert _toml(project_dir)["flow"]["skip_steps"] == ["diff_opt"]


@pytest.mark.parametrize(
    ("args", "keys"),
    [([], ["\r", "y"]), (["--disable", "diff_opt", "--yes"], [])],
)
def test_a_policy_skipping_the_flow_target_is_edited_with_it_enabled(
    capsys, monkeypatch, create_cli_project, set_flow_preset, args, keys
):
    # The default policy skips lec, which ends the synthesis_lec preset.
    project_dir = create_cli_project()
    set_flow_preset(project_dir, "synthesis_lec")
    _scripted_terminal(monkeypatch, keys)

    rc = cli_main.run(["flow", "edit", "--project", project_dir, *args])

    assert rc == 0
    assert "  enabled: lec" in capsys.readouterr().out
    assert _toml(project_dir)["flow"]["skip_steps"] == []


@pytest.mark.parametrize("answer", ["n", "\r", "q"])
def test_declined_selection_is_not_written(capsys, monkeypatch, create_cli_project, answer):
    project_dir = create_cli_project()
    with open(os.path.join(project_dir, "ecc.toml")) as f:
        before = f.read()
    _scripted_terminal(monkeypatch, ["\x1b[B ", "\r", answer])

    rc = cli_main.run(["flow", "edit", "--project", project_dir])

    assert rc == 0
    assert "No changes written." in capsys.readouterr().out
    with open(os.path.join(project_dir, "ecc.toml")) as f:
        assert f.read() == before


@pytest.mark.parametrize(
    ("args", "mismatch"),
    [
        # A ledger without CTS cannot grow it in the middle.
        (["--enable", "CTS"], True),
        # Newly skipped steps stay inert in an existing ledger.
        (["--disable", "emir"], False),
    ],
)
def test_existing_workspaces_the_selection_contradicts_are_reported(
    capsys, create_cli_project, args, mismatch
):
    project_dir = create_cli_project()
    _edit(capsys, project_dir, "--disable", "CTS", "--yes")
    home = os.path.join(project_dir, "default", "home")
    os.makedirs(home)
    ledger = build_dynamic_flow_data(
        {"preset": "rtl2gds", "skip_steps": [*DEFAULT_SKIP_STEPS, "CTS"]}
    )
    with open(os.path.join(home, "flow.json"), "w") as f:
        json.dump(ledger, f)

    rc, records = _edit(capsys, project_dir, *args, "--yes")

    assert rc == 0
    mismatches = [
        record for record in records if record.get("warning") == "workspace_flow_mismatch"
    ]
    assert [record["workspace_id"] for record in mismatches] == (["default"] if mismatch else [])


def test_plain_records_state_the_written_selection(capsys, create_cli_project):
    project_dir = create_cli_project()

    rc = cli_main.run(
        ["flow", "edit", "--project", project_dir, "--plain", "--disable", "CTS", "--yes"]
    )

    assert rc == 0
    assert capsys.readouterr().out.splitlines() == [
        f"record=flow_edit status=written path={os.path.join(project_dir, 'ecc.toml')} "
        "preset=rtl2gds lec_engine=kepler_formal skip_steps=\"['lec', 'diff_opt', 'CTS']\" "
        "enabled=[] disabled=['CTS']",
        *(
            f"kind=warning warning=flow_step_degraded step={step} missing=['clock_tree'] "
            f"fixes=['CTS'] reason=\"{step} runs with degraded results without clock_tree; "
            'enable CTS"'
            for step in ("route", "sta", "powerAnalysis", "Harden")
        ),
    ]
