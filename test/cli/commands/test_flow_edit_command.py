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
        "skip_steps": ["CTS"],
        "insert_steps": [],
        "max_parallel_steps": 4,
        "enabled": ["diff_opt"],
        "disabled": ["CTS"],
        "inserted": [],
        "removed": [],
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
        "skip_steps": ["CTS"],
        "max_parallel_steps": 4,
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


def _declare_max_parallel_steps(project_dir, value):
    # [flow] is the last table of the project fixture.
    with open(os.path.join(project_dir, "ecc.toml"), "a") as f:
        f.write(f"max_parallel_steps = {value}\n")


def test_max_parallel_steps_alone_is_written_and_the_rest_of_ecc_toml_stays(
    capsys, create_cli_project
):
    project_dir = create_cli_project()
    before = _toml(project_dir)

    rc, records = _edit(capsys, project_dir, "--max-parallel-steps", "1", "--yes")

    assert rc == 0
    assert records == [
        {
            "record": "flow_edit",
            "status": "written",
            "path": os.path.join(project_dir, "ecc.toml"),
            "preset": "rtl2gds",
            "lec_engine": "kepler_formal",
            "skip_steps": ["diff_opt"],
            "insert_steps": [],
            "max_parallel_steps": 1,
            "enabled": [],
            "disabled": [],
            "inserted": [],
            "removed": [],
        }
    ]
    after = _toml(project_dir)
    assert after["flow"] == {
        "preset": "rtl2gds",
        "lec_engine": "kepler_formal",
        "skip_steps": ["diff_opt"],
        "max_parallel_steps": 1,
    }
    assert {key: value for key, value in after.items() if key != "flow"} == {
        key: value for key, value in before.items() if key != "flow"
    }


def test_toggles_keep_the_projects_current_max_parallel_steps(capsys, create_cli_project):
    project_dir = create_cli_project()
    _declare_max_parallel_steps(project_dir, 2)

    rc, records = _edit(capsys, project_dir, "--disable", "CTS", "--yes")

    assert rc == 0
    assert records[0]["max_parallel_steps"] == 2
    assert _toml(project_dir)["flow"]["max_parallel_steps"] == 2


def test_the_flag_and_toggles_are_written_together(capsys, create_cli_project):
    project_dir = create_cli_project()

    rc, records = _edit(
        capsys, project_dir, "--disable", "CTS", "--max-parallel-steps", "3", "--yes"
    )

    assert rc == 0
    assert (records[0]["disabled"], records[0]["max_parallel_steps"]) == (["CTS"], 3)
    flow = _toml(project_dir)["flow"]
    assert (flow["skip_steps"], flow["max_parallel_steps"]) == (["diff_opt", "CTS"], 3)


def test_max_parallel_steps_without_a_terminal_needs_yes(capsys, create_cli_project):
    project_dir = create_cli_project()
    with open(os.path.join(project_dir, "ecc.toml")) as f:
        before = f.read()

    rc, records = _edit(capsys, project_dir, "--max-parallel-steps", "2")

    assert rc == 1
    assert [record["error"] for record in records] == ["flow_edit_requires_confirmation"]
    with open(os.path.join(project_dir, "ecc.toml")) as f:
        assert f.read() == before


@pytest.mark.parametrize("value", ["0", "-1", "two"])
def test_an_invalid_max_parallel_steps_is_rejected_and_nothing_is_written(
    capsys, create_cli_project, value
):
    project_dir = create_cli_project()
    with open(os.path.join(project_dir, "ecc.toml")) as f:
        before = f.read()

    rc = cli_main.run(
        ["flow", "edit", "--project", project_dir, "--max-parallel-steps", value, "--yes"]
    )

    assert rc == 2
    assert "Invalid value for '--max-parallel-steps'" in capsys.readouterr().err
    with open(os.path.join(project_dir, "ecc.toml")) as f:
        assert f.read() == before


def test_the_flag_with_a_selection_missing_required_data_is_not_written(capsys, create_cli_project):
    project_dir = create_cli_project()
    with open(os.path.join(project_dir, "ecc.toml")) as f:
        before = f.read()

    rc, records = _edit(
        capsys,
        project_dir,
        "--disable",
        "legalization",
        "--disable",
        "TimingOpt",
        "--max-parallel-steps",
        "2",
        "--yes",
    )

    assert rc == 1
    assert [record["error"] for record in records] == ["flow_selection_invalid"]
    with open(os.path.join(project_dir, "ecc.toml")) as f:
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


#: Down from Synthesis to diff_opt, the one step skipped by default.
_TO_DIFF_OPT = "\x1b[B" * 6


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
        # One read may hold several keys: enable diff_opt (row 7), save, confirm.
        ([], [_TO_DIFF_OPT + " ", "\r", "y"]),
        (["--enable", "diff_opt"], ["y"]),
        (["--yes"], [_TO_DIFF_OPT + " ", "\r"]),
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
    assert _toml(project_dir)["flow"]["skip_steps"] == []


def test_the_checkbox_saves_the_chosen_max_parallel_steps(capsys, monkeypatch, create_cli_project):
    project_dir = create_cli_project()
    # Lower the value twice, save, confirm.
    _scripted_terminal(monkeypatch, ["\x1b[D\x1b[D", "\r", "y"])

    rc = cli_main.run(["flow", "edit", "--project", project_dir])

    assert rc == 0
    out = capsys.readouterr().out
    assert "  max_parallel_steps = 2" in out.splitlines()
    assert _toml(project_dir)["flow"] == {
        "preset": "rtl2gds",
        "lec_engine": "kepler_formal",
        "skip_steps": ["diff_opt"],
        "max_parallel_steps": 2,
    }


@pytest.mark.parametrize("keys", [["\r", "y"], [_TO_DIFF_OPT + " ", "\r", "y"]])
def test_the_checkbox_keeps_the_current_value_unless_asked(
    capsys, monkeypatch, create_cli_project, keys
):
    project_dir = create_cli_project()
    _declare_max_parallel_steps(project_dir, 3)
    _scripted_terminal(monkeypatch, keys)

    rc = cli_main.run(["flow", "edit", "--project", project_dir])

    assert rc == 0
    assert "  max_parallel_steps = 3" in capsys.readouterr().out.splitlines()
    assert _toml(project_dir)["flow"]["max_parallel_steps"] == 3


@pytest.mark.parametrize("answer", ["y", "n"])
def test_the_terminal_flag_change_is_confirmed_before_it_is_written(
    capsys, monkeypatch, create_cli_project, answer
):
    project_dir = create_cli_project()
    _scripted_terminal(monkeypatch, [answer])

    rc = cli_main.run(["flow", "edit", "--project", project_dir, "--max-parallel-steps", "2"])

    assert rc == 0
    assert _toml(project_dir)["flow"].get("max_parallel_steps") == (2 if answer == "y" else None)


@pytest.mark.parametrize(
    ("args", "keys"),
    [([], ["\r", "y"]), (["--disable", "diff_opt", "--yes"], [])],
)
def test_a_policy_skipping_the_flow_target_is_edited_with_it_enabled(
    capsys, monkeypatch, create_cli_project, set_flow_preset, args, keys
):
    # syn_sta ends at Synthesis, which this policy skips.
    project_dir = create_cli_project()
    set_flow_preset(project_dir, "syn_sta")
    with open(os.path.join(project_dir, "ecc.toml"), "a") as f:
        f.write('skip_steps = ["Synthesis"]\n')
    _scripted_terminal(monkeypatch, keys)

    rc = cli_main.run(["flow", "edit", "--project", project_dir, *args])

    assert rc == 0
    assert "  enabled: Synthesis" in capsys.readouterr().out
    assert _toml(project_dir)["flow"]["skip_steps"] == []


@pytest.mark.parametrize("answer", ["n", "\r", "q"])
def test_declined_selection_is_not_written(capsys, monkeypatch, create_cli_project, answer):
    project_dir = create_cli_project()
    with open(os.path.join(project_dir, "ecc.toml")) as f:
        before = f.read()
    _scripted_terminal(monkeypatch, [_TO_DIFF_OPT + " ", "\r", answer])

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
        "preset=rtl2gds lec_engine=kepler_formal skip_steps=\"['diff_opt', 'CTS']\" "
        "insert_steps=[] max_parallel_steps=4 enabled=[] disabled=['CTS'] inserted=[] removed=[]",
        *(
            f"kind=warning warning=flow_step_degraded step={step} missing=['clock_tree'] "
            f"fixes=['CTS'] reason=\"{step} runs with degraded results without clock_tree; "
            'enable CTS"'
            for step in ("route", "sta", "powerAnalysis", "Harden")
        ),
    ]
