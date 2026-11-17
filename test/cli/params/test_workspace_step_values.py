"""Workspace-scope commands on per-step (DreamPlace) parameter values."""

from pathlib import Path

import pytest

from chipcompiler.cli import main as cli_main
from test.cli.params.test_workspace_commands import _Flow, _workspace, _write_manifest


@pytest.fixture
def managed_workspace(create_cli_project, monkeypatch):
    """``(project_dir, workspace)``: synthesis, placement, diff_opt, routing, all run."""
    project_dir = create_cli_project()
    _write_manifest(project_dir)
    workspace = _workspace(Path(project_dir) / "baseline")
    steps = workspace.flow.data["steps"]
    steps.insert(
        2, {**steps[1], "name": "diff_opt", "directory": "diff_opt_dreamplace", "state": "Success"}
    )
    monkeypatch.setattr("chipcompiler.data.load_workspace", lambda _path: workspace)
    monkeypatch.setattr("chipcompiler.data.refresh_workspace_config", lambda _workspace: None)
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", _Flow)
    return project_dir, workspace


def _run(project_dir: str, *args: str) -> int:
    return cli_main.run(
        ["param", *args, "--workspace", "baseline", "--project", project_dir, "--plain"]
    )


def _error(capsys, plain_records) -> str:
    captured = capsys.readouterr()
    return plain_records(captured.out + captured.err)[0]["error"]


def test_a_diff_opt_value_invalidates_from_diff_opt_and_keeps_placement(
    managed_workspace, capsys, plain_records
) -> None:
    project_dir, workspace = managed_workspace

    assert _run(project_dir, "set", "diff_opt:place.timing_sizing_action", "up") == 0

    record = plain_records(capsys.readouterr().out)[0]
    assert (record["from_step"], record["invalidated_steps"]) == (
        "diff_opt",
        "['diff_opt', 'routing']",
    )
    assert {step["name"]: step["state"] for step in workspace.flow.data["steps"]} == {
        "synthesis": "Success",
        "placement": "Success",
        "diff_opt": "Unstart",
        "routing": "Unstart",
    }
    assert workspace.parameters.data["step_params"] == {
        "diff_opt": {"place.timing_sizing_action": "up"}
    }


@pytest.mark.parametrize(
    ("key", "error"),
    [
        ("legalization:place.target_density", "parameter_not_applicable"),
        ("place.target_density", "parameter_step_required"),
    ],
)
def test_a_dreamplace_value_needs_one_of_its_steps(
    managed_workspace, capsys, plain_records, key, error
) -> None:
    project_dir, workspace = managed_workspace

    assert _run(project_dir, "set", key, "0.6") == 1

    assert _error(capsys, plain_records) == error
    assert "step_params" not in workspace.parameters.data


def test_a_step_value_for_a_step_outside_the_flow_is_rejected(
    managed_workspace, capsys, plain_records
) -> None:
    project_dir, workspace = managed_workspace
    workspace.flow.data["steps"] = [
        step for step in workspace.flow.data["steps"] if step["name"] != "diff_opt"
    ]

    assert _run(project_dir, "set", "diff_opt:place.timing_sizing_action", "up") == 1

    assert _error(capsys, plain_records) == "unknown_flow_step"
    assert "step_params" not in workspace.parameters.data


def test_show_needs_the_step_of_a_dreamplace_parameter(
    managed_workspace, capsys, plain_records
) -> None:
    project_dir, _ = managed_workspace

    assert _run(project_dir, "show", "place.target_density") == 1

    assert _error(capsys, plain_records) == "parameter_step_required"


def test_list_without_a_step_shows_edited_and_with_all_every_stored_step_value(
    managed_workspace, capsys, plain_records
) -> None:
    project_dir, workspace = managed_workspace
    assert _run(project_dir, "set", "placement:place.target_density", "0.65") == 0
    # A value stored at creation (``ecc.toml`` / ``--set``) has no journal record.
    workspace.parameters.data["step_params"]["diff_opt"] = {"place.target_density": 0.5}
    capsys.readouterr()

    def step_rows(*args: str) -> list[tuple[str, str, str, str]]:
        assert _run(project_dir, "list", *args) == 0
        return [
            (record["id"], record["step_id"], record["value_literal"], record["status"])
            for record in plain_records(capsys.readouterr().out)
            if "step_id" in record
        ]

    assert step_rows() == [("place.target_density", "placement", "0.65", "workspace")]
    assert step_rows("--all") == [
        ("place.target_density", "placement", "0.65", "workspace"),
        ("place.target_density", "diff_opt", "0.5", "base"),
    ]
