"""[flow] insert_steps: an LEC inserted after a design-building step (``lec@CTS``)."""

import json
import os
import tomllib

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.inspection import env_probe
from chipcompiler.cli.project.config import load_project_config, validate_project_config
from chipcompiler.data import DEFAULT_SKIP_STEPS, StateEnum
from chipcompiler.rtl2gds.builder import build_rtl2gds_flow as _build_rtl2gds_flow


@pytest.fixture(autouse=True)
def _pdk_contents_are_valid(monkeypatch):
    monkeypatch.setattr(
        "chipcompiler.cli.project.config._validate_pdk_contents",
        lambda name, root, overrides=None: None,
    )


def _declare(project_dir, literal):
    # The fixture project's ecc.toml ends with its [flow] table.
    with open(os.path.join(project_dir, "ecc.toml"), "a") as f:
        f.write(f"insert_steps = {literal}\n")


def _flow_table(project_dir):
    with open(os.path.join(project_dir, "ecc.toml"), "rb") as f:
        return tomllib.load(f)["flow"]


def _run(capsys, *argv):
    rc = cli_main.run([*argv, "--json"])
    return rc, json.loads(capsys.readouterr().out)


def test_plan_shows_the_inserted_lec_after_the_step_it_checks(capsys, create_cli_project):
    project_dir = create_cli_project()

    rc, records = _run(capsys, "flow", "plan", "--project", project_dir, "--insert", "lec@cts")

    steps = [record for record in records if record["record"] == "flow_step"]
    names = [step["step"] for step in steps]
    cts = names.index("CTS")
    assert (rc, records[0]["insert_steps"], names[cts + 1]) == (0, ["lec@CTS"], "lec@CTS")
    assert steps[cts + 1] == {
        "record": "flow_step",
        "position": cts + 2,
        "step": "lec@CTS",
        "tool": "kepler_formal",
        "enabled": True,
        "optional": True,
        "target": False,
        "requires": ["golden_netlist", "netlist"],
        "uses": [],
        "provides": [],
        "stage": steps[cts]["stage"] + 1,
        "slot": "",
        "label": str(steps[cts]["stage"] + 1),
        "parallel_with": [],
        "after": ["CTS", "Synthesis"],
        "needs": {"golden_netlist": "Synthesis", "netlist": "Synthesis"},
        "check": False,
        "inserted": True,
    }


def test_an_inserted_lec_is_skipped_with_its_step(capsys, create_cli_project):
    project_dir = create_cli_project()
    _declare(project_dir, '["lec@CTS"]')

    rc, records = _run(capsys, "flow", "plan", "--project", project_dir, "--disable", "CTS")

    enabled = {
        record["step"]: record["enabled"] for record in records if record["record"] == "flow_step"
    }
    assert (rc, enabled["CTS"], enabled["lec@CTS"], records[0]["skip_steps"]) == (
        0,
        False,
        False,
        [*DEFAULT_SKIP_STEPS, "CTS"],
    )


def test_edit_writes_and_removes_insert_steps(capsys, create_cli_project):
    project_dir = create_cli_project()
    edit = ("flow", "edit", "--project", project_dir, "--yes")

    inserted = _run(capsys, *edit, "--insert", "lec@route", "--insert", "lec@timing_opt")
    written = _flow_table(project_dir)
    removed = _run(capsys, *edit, "--remove", "lec@route", "--remove", "lec@Timing_optimization")

    assert (inserted[0], inserted[1][0]["inserted"], written["insert_steps"]) == (
        0,
        ["lec@Timing_optimization", "lec@route"],
        ["lec@Timing_optimization", "lec@route"],
    )
    assert (removed[0], removed[1][0]["removed"], "insert_steps" in _flow_table(project_dir)) == (
        0,
        ["lec@Timing_optimization", "lec@route"],
        False,
    )


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        (("--insert", "drc@CTS"), "insert_steps entry 'drc@CTS': only lec can be inserted"),
        (("--remove", "lec@CTS"), "steps not inserted, nothing to remove: lec@CTS"),
        (
            ("--insert", "lec@CTS", "--remove", "lec@cts"),
            "steps both inserted and removed: lec@CTS",
        ),
    ],
)
def test_edit_rejects_an_invalid_insertion_without_writing(
    capsys, create_cli_project, args, reason
):
    project_dir = create_cli_project()
    before = _flow_table(project_dir)

    rc, records = _run(capsys, "flow", "edit", "--project", project_dir, "--yes", *args)

    assert (rc, records, _flow_table(project_dir)) == (
        1,
        [{"kind": "error", "error": "flow_selection_invalid", "reason": reason}],
        before,
    )


def test_check_rejects_an_invalid_declared_insertion(create_cli_project):
    project_dir = create_cli_project()
    _declare(project_dir, '["lec@filler"]')

    errors = validate_project_config(load_project_config(os.path.join(project_dir, "ecc.toml")))

    assert [error for error in errors if "insert_steps" in error] == [
        "insert_steps entry 'lec@filler': lec can be inserted after Synthesis, preFloorplan, "
        "macroPlacement, postFloorplan, preplace, place, diff_opt, diff_sizing, CTS, "
        "legalization, Timing optimization, route"
    ]


def test_config_reports_the_declared_and_resolved_insertions(capsys, create_cli_project):
    project_dir = create_cli_project()
    _declare(project_dir, '["lec@cts"]')

    rc, records = _run(capsys, "config", "--project", project_dir)

    (entry,) = [record for record in records if record.get("config") == "flow.insert_steps"]
    assert (rc, entry["value"], entry["resolved"], entry["source"]) == (
        0,
        ["lec@cts"],
        ["lec@CTS"],
        "ecc.toml",
    )


def test_config_reports_the_synthesis_lec_a_project_json_entry_implies(capsys, create_cli_project):
    project_dir = create_cli_project()
    workspace = {
        "workspace_id": "ws_0001",
        "workspace_path": os.path.join(project_dir, "ws_0001"),
        "status": "not_started",
        "start_step": "Synth",
        "end_step": "Harden",
        # project.json still lists LEC as a step: keeping it inserts lec@Synthesis.
        "skip_steps": ["DiffOpt"],
    }
    with open(os.path.join(project_dir, "project.json"), "w") as f:
        json.dump(
            {
                "schema_version": 1,
                "design_name": "gcd",
                "root_path": project_dir,
                "workspaces": [workspace],
            },
            f,
        )

    rc, records = _run(capsys, "config", "--project", project_dir, "--workspace", "ws_0001")

    (entry,) = [record for record in records if record.get("config") == "flow.insert_steps"]
    assert (rc, entry["value"], entry["resolved"], entry["source"]) == (
        0,
        ["lec@Synthesis"],
        ["lec@Synthesis"],
        "project.json",
    )


def test_a_fresh_run_creates_the_inserted_lec_after_its_step(
    capsys, monkeypatch, create_cli_project, flow_mocks
):
    monkeypatch.setattr("chipcompiler.rtl2gds.builder.build_rtl2gds_flow", _build_rtl2gds_flow)
    project_dir = create_cli_project()
    _declare(project_dir, '["lec@CTS"]')

    assert cli_main.run(["run", "--project", project_dir]) == 0

    (flow,) = flow_mocks.flow.instances
    added = [
        (str(getattr(step, "value", step)), tool, state) for step, tool, state in flow.added_steps
    ]
    cts = [name for name, _tool, _state in added].index("CTS")
    assert (flow_mocks.capture["create_kwargs"]["flow_config"], added[cts + 1]) == (
        {"insert_steps": ["lec@CTS"]},
        ("lec@CTS", "kepler_formal", StateEnum.Unstart),
    )


def test_preflight_probes_the_lec_engine_for_an_inserted_lec_alone():
    skip = (*DEFAULT_SKIP_STEPS, "postRouteLec")

    assert (
        "kepler-formal" in env_probe.probe_components_for_preset("rtl2gds", skip=skip),
        "kepler-formal"
        in env_probe.probe_components_for_preset("rtl2gds", skip=skip, insert=("lec@CTS",)),
    ) == (False, True)
