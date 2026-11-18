"""Every per-step parameter view of an rtl2gds flow lists the same parameters."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.command_handlers import workspace_params
from chipcompiler.cli.command_handlers.param_edit import _row_listed_at, workspace_rows
from chipcompiler.cli.core.types import CommandContext, OutputMode
from chipcompiler.data.step_parameters import split_step_key
from chipcompiler.engine import create_workspace_from_spec
from chipcompiler.engine.parameter_steps import step_catalog
from chipcompiler.params import list_schemas
from chipcompiler.params.evidence import build_step_parameter_record

_FIXTURES = Path(__file__).parents[2] / "fixtures" / "workspace_spec"


@pytest.fixture
def rtl2gds_workspace(tmp_path, minimal_ics55_pdk_factory):
    payload = json.loads((_FIXTURES / "valid.json").read_text(encoding="utf-8"))
    bindings = deepcopy(payload["workspaceBindings"])
    bindings["inputs"] = {key: str(_FIXTURES / value) for key, value in bindings["inputs"].items()}
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    return create_workspace_from_spec(
        tmp_path / "workspace", payload["workspaceSpec"], bindings, "create-1"
    )


def _param(key: str) -> str:
    return split_step_key(key)[1]


def _project_list(project: Path, step: str, capsys, plain_records) -> set[str]:
    capsys.readouterr()
    assert (
        cli_main.run(["param", "list", "--step", step, "--project", str(project), "--plain"]) == 0
    )
    return {_param(record["param"]) for record in plain_records(capsys.readouterr().out)}


def _project_editor(project: Path, step: str, scripted_terminal, monkeypatch) -> set[str]:
    shown: list = []

    def capture(rows, **_kwargs):
        shown.extend(rows)
        return None  # cancel

    monkeypatch.setattr("chipcompiler.cli.interactive.param_edit.edit_parameters", capture)
    scripted_terminal([])
    rc = cli_main.run(["param", "edit", "--step", step, "--project", str(project)])
    # A step without parameters never opens the editor.
    assert rc == (0 if shown else 1)
    return {_param(row.param) for row in shown}


def test_all_step_views_agree_on_the_parameters_of_each_step(
    ready_project, rtl2gds_workspace, capsys, plain_records, scripted_terminal, monkeypatch
) -> None:
    workspace = rtl2gds_workspace
    ctx = CommandContext(
        project_dir=str(ready_project),
        project=None,
        run_dir=str(workspace.directory),
        run_id="workspace",
        output_mode=OutputMode.PLAIN,
        project_state="manifest",
    )
    flow = [(step["name"], step["tool"]) for step in workspace.flow.steps()]
    first = flow[0][0]
    rows = workspace_rows(ctx)
    assert isinstance(rows, list)
    workspace_wide = {
        schema.param
        for schema in list_schemas()
        if schema.workspace_wide and schema.pdk_target is None
    }

    for step, tool in flow:
        catalog = {schema.param for schema in step_catalog(workspace, step)[1]}
        listed = workspace_params.param_list(SimpleNamespace(step=step, all=True), ctx)
        views = {
            "project list": _project_list(ready_project, step, capsys, plain_records),
            "project editor": _project_editor(ready_project, step, scripted_terminal, monkeypatch),
            "workspace list": {record["id"] for record in listed.records if "id" in record},
            "workspace editor": {
                _param(row.param) for row in rows if _row_listed_at(row, step, first)
            },
        }
        evidence = {
            item["param"]
            for item in build_step_parameter_record(workspace, step, tool)["parameters"]
        }

        assert views == dict.fromkeys(views, catalog), step
        # Run evidence also records the workspace-wide inputs of every step.
        assert evidence == (catalog - workspace_wide) | workspace_wide, step
