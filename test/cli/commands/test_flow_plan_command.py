"""`ecc flow plan`: the project's step selection, as records and as a checklist."""

import json
import os

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.core.completion import complete_flow_step
from chipcompiler.data import DEFAULT_SKIP_STEPS


def _plan(capsys, project_dir, *args):
    rc = cli_main.run(["flow", "plan", "--project", project_dir, "--json", *args])
    return rc, json.loads(capsys.readouterr().out)


def _records(records, kind):
    return [record for record in records if record["record"] == kind]


def test_default_selection_lists_every_step_of_the_preset(capsys, create_cli_project):
    rc, records = _plan(capsys, create_cli_project())

    assert rc == 0
    assert records[0] == {
        "record": "flow_plan",
        "flow": "rtl2gds",
        "status": "ok",
        "enabled_count": 21,
        "step_count": 22,
        "skip_steps": list(DEFAULT_SKIP_STEPS),
        "insert_steps": [],
        "max_parallel_steps": 4,
    }
    steps = _records(records, "flow_step")
    assert [step["step"] for step in steps if not step["enabled"]] == list(DEFAULT_SKIP_STEPS)
    assert next(step for step in steps if step["step"] == "route") == {
        "record": "flow_step",
        "position": 12,
        "step": "route",
        "tool": "ecc",
        "enabled": True,
        "optional": False,
        "target": False,
        "requires": ["legal"],
        "uses": ["clock_tree"],
        "provides": ["routed"],
        "stage": 11,
        "slot": "",
        "label": "11",
        "parallel_with": [],
        "after": ["Timing optimization", "CTS"],
        "needs": {"clock_tree": "CTS", "legal": "Timing optimization"},
        "check": False,
        "inserted": False,
    }
    assert [step["step"] for step in steps if step["target"]] == ["Harden"]
    assert _records(records, "flow_violation") == []


def test_a_disabled_step_has_a_null_stage_and_the_later_stages_renumber(capsys, create_cli_project):
    rc, records = _plan(capsys, create_cli_project(), "--disable", "drc")

    assert rc == 0
    steps = {step["step"]: step for step in _records(records, "flow_step")}
    assert steps["drc"] == {
        "record": "flow_step",
        "position": 15,
        "step": "drc",
        "tool": "ecc",
        "enabled": False,
        "optional": False,
        "target": False,
        "requires": ["filled"],
        "uses": [],
        "provides": [],
        "stage": None,
        "slot": "",
        "label": "",
        "parallel_with": [],
        "after": ["filler"],
        "needs": {"filled": "filler"},
        "check": True,
        "inserted": False,
    }
    assert steps["lvs"]["parallel_with"] == ["antennaCheck", "postRouteLec", "RCX"]
    assert steps["Harden"]["stage"] == 16


def _declare_max_parallel_steps(project_dir, value):
    # [flow] is the last table of the project fixture.
    with open(os.path.join(project_dir, "ecc.toml"), "a") as f:
        f.write(f"max_parallel_steps = {value}\n")


def test_the_summary_reports_the_projects_max_parallel_steps(capsys, create_cli_project):
    project_dir = create_cli_project()
    _declare_max_parallel_steps(project_dir, 2)

    rc, records = _plan(capsys, project_dir)

    assert rc == 0
    assert records[0] == {
        "record": "flow_plan",
        "flow": "rtl2gds",
        "status": "ok",
        "enabled_count": 21,
        "step_count": 22,
        "skip_steps": list(DEFAULT_SKIP_STEPS),
        "insert_steps": [],
        "max_parallel_steps": 2,
    }


@pytest.mark.parametrize(
    ("value", "legend"),
    [
        (None, "┐…┘ same number = can run in parallel, up to 4 at once"),
        (3, "┐…┘ same number = can run in parallel, up to 3 at once"),
        (1, "┐…┘ same number = independent steps; run one at a time (max_parallel_steps = 1)"),
    ],
)
def test_the_table_legend_states_the_projects_value(capsys, create_cli_project, value, legend):
    project_dir = create_cli_project()
    if value is not None:
        _declare_max_parallel_steps(project_dir, value)

    rc = cli_main.run(["flow", "plan", "--project", project_dir])

    assert rc == 0
    assert legend in capsys.readouterr().out.splitlines()


def test_overrides_are_checked_without_writing_the_project(capsys, create_cli_project):
    project_dir = create_cli_project()
    toml_path = os.path.join(project_dir, "ecc.toml")
    with open(toml_path) as f:
        before = f.read()

    rc, records = _plan(capsys, project_dir, "--disable", "legalization", "--disable", "TimingOpt")

    assert rc == 1
    assert records[0]["status"] == "error"
    assert _records(records, "flow_violation") == [
        {
            "record": "flow_violation",
            "severity": "error",
            "step": "route",
            "missing": ["legal"],
            "fixes": ["Timing optimization", "legalization"],
            "reason": "route requires legal; enable Timing optimization or legalization",
        }
    ]
    with open(toml_path) as f:
        assert f.read() == before


def test_unchecked_synthesis_needs_a_declared_netlist(capsys, create_cli_project):
    rc, records = _plan(capsys, create_cli_project(), "--disable", "synth")

    assert rc == 1
    assert records[0]["skip_steps"] == ["Synthesis", *DEFAULT_SKIP_STEPS]
    assert _records(records, "flow_input") == [
        {
            "record": "flow_input",
            "severity": "error",
            "step": "preFloorplan",
            "reason": "step_input_missing: preFloorplan requires design.netlist",
        }
    ]


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        (["--disable", "Harden"], "'Harden' ends the flow and cannot be skipped"),
        (["--enable", "CTS", "--disable", "cts"], "steps both enabled and disabled: CTS"),
        (["--enable", "lec"], "lec is not a flow step to enable or disable"),
        (["--disable", "Spin"], "skip_steps names unknown flow steps: Spin"),
    ],
)
def test_invalid_overrides_are_rejected(capsys, create_cli_project, args, reason):
    rc, records = _plan(capsys, create_cli_project(), *args)

    assert rc == 1
    assert records[0]["error"] == "flow_selection_invalid"
    assert records[0]["reason"].startswith(reason)


def test_text_mode_prints_the_checklist_and_its_warnings(capsys, create_cli_project):
    rc = cli_main.run(["flow", "plan", "--project", create_cli_project(), "--disable", "CTS"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "rtl2gds · 20 of 22 steps enabled" in out
    assert "! warning: route runs with degraded results without clock_tree; enable CTS" in out


@pytest.mark.parametrize(
    ("incomplete", "expected"),
    [
        ("ti", ["Timing optimization"]),
        ("PO", ["postFloorplan", "postRouteLec", "powerAnalysis"]),
        ("zz", []),
    ],
)
def test_step_options_complete_canonical_step_names(incomplete, expected):
    assert complete_flow_step(incomplete) == expected


def test_plain_records_name_the_missing_design_data(capsys, create_cli_project):
    rc = cli_main.run(
        ["flow", "plan", "--project", create_cli_project(), "--plain", "--disable", "CTS"]
    )

    assert rc == 0
    assert [
        line for line in capsys.readouterr().out.splitlines() if "record=flow_violation" in line
    ] == [
        f"record=flow_violation severity=warning step={step} missing=['clock_tree'] "
        f"fixes=['CTS'] reason=\"{step} runs with degraded results without clock_tree; "
        'enable CTS"'
        for step in ("route", "sta", "powerAnalysis", "Harden")
    ]
