"""Tests for `ecc flow workspace` inspection of a Workspace's recorded ledger."""

import json

from chipcompiler.cli import main as cli_main


def test_workspace_flow_plan_reads_the_selected_ledger(fresh_project, capsys):
    assert cli_main.run(["workspace", "create", "trimmed", "--project", str(fresh_project)]) == 0
    assert cli_main.run(["workspace", "create", "other", "--project", str(fresh_project)]) == 0
    flow_json = fresh_project / "trimmed" / "home" / "flow.json"
    info = json.loads(flow_json.read_text())
    info["steps"] = [
        {"name": "filler", "tool": "ecc", "category": "PNR"},
        {"name": "rcx", "tool": "ecc", "category": "CHECKER"},
        {"name": "drc", "tool": "ecc", "category": "CHECKER", "input_step": "rcx"},
    ]
    for index, step in enumerate(info["steps"]):
        step.update(state="Unstart", directory=f"{index}_{step['name']}")
    flow_json.write_text(json.dumps(info))
    original = flow_json.read_bytes()
    capsys.readouterr()

    assert (
        cli_main.run(["flow", "workspace", "trimmed", "--project", str(fresh_project), "--json"])
        == 0
    )
    header, *steps = json.loads(capsys.readouterr().out)
    assert header["workspace_id"] == "trimmed"
    assert [(row["step"], row["stage"], row["design_source"]) for row in steps] == [
        ("filler", 1, None),
        ("rcx", 2, "filler"),
        ("drc", 3, "rcx"),
    ]
    assert steps[1]["needs"]["filled"] == "filler"
    assert flow_json.read_bytes() == original


def test_workspace_flow_plan_rejects_malformed_step_records(fresh_project, capsys):
    import pytest

    from chipcompiler.cli.inspection.flow import plan_records

    with pytest.raises(ValueError, match="Invalid step record"):
        plan_records([{"name": "synthesis"}])

    assert cli_main.run(["workspace", "create", "broken", "--project", str(fresh_project)]) == 0
    flow_json = fresh_project / "broken" / "home" / "flow.json"
    info = json.loads(flow_json.read_text())
    info["steps"] = [{"name": "synthesis"}]
    flow_json.write_text(json.dumps(info))
    capsys.readouterr()

    assert (
        cli_main.run(["flow", "workspace", "broken", "--project", str(fresh_project), "--json"])
        == 1
    )
    (record,) = json.loads(capsys.readouterr().out)
    assert record["error"] in {"workspace_flow_invalid", "workspace_flow_unavailable"}


def test_skipped_step_remains_visible_and_supplies_no_design_inputs():
    from chipcompiler.cli.inspection.flow import plan_records

    steps = plan_records(
        [
            {"name": "legalization", "tool": "ecc", "category": "PNR", "state": "Success"},
            {"name": "timing_optimization", "tool": "sizer", "category": "PNR", "state": "Skipped"},
            {"name": "routing", "tool": "ecc", "category": "PNR", "state": "Unstart"},
        ]
    )
    assert [step["step"] for step in steps] == ["legalization", "timing_optimization", "routing"]
    assert steps[-1]["design_source"] == steps[-1]["needs"]["legal"] == "legalization"
