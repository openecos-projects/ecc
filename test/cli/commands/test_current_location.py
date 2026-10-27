import json

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.core.inputs import OutputOptions, ProjectOptions, StatusInput
from chipcompiler.cli.core.invocation import apply_location_defaults, build_context
from chipcompiler.cli.core.types import CommandResult


@pytest.fixture
def location_project(tmp_path, manifest_stubs):
    project = tmp_path / "project"
    project.mkdir()
    current = project / "physical_directory"
    other = project / "other"
    for root in (current, other):
        (root / "home").mkdir(parents=True)
        (root / "home" / "flow.json").write_text(
            json.dumps({"steps": [{"name": "drc", "tool": "ecc", "state": "Success"}]})
        )
    entry = manifest_stubs.entry(project, "registered_alias")
    entry["workspace_path"] = str(current)
    manifest_stubs.write(project, [entry, manifest_stubs.entry(project, "other")])
    return project, current, other


def _input(*, project=None, workspace=None):
    return StatusInput(
        output=OutputOptions(json=True), project=ProjectOptions(project), workspace=workspace
    )


def test_project_root_uses_current_directory_without_guessing_workspace(
    location_project, monkeypatch
):
    project, _current, _other = location_project
    monkeypatch.chdir(project)

    command_input = apply_location_defaults(_input())
    ctx = build_context(command_input)

    assert command_input == _input()
    assert ctx.project_dir == str(project)
    assert ctx.manifest_error is not None
    assert ctx.manifest_error.startswith("workspace_required:")


def test_workspace_root_selects_registered_id_not_directory_name(location_project, monkeypatch):
    project, current, _other = location_project
    monkeypatch.chdir(current)

    command_input = apply_location_defaults(_input())
    ctx = build_context(_input())

    assert command_input == _input(project=str(project), workspace="registered_alias")
    assert (ctx.project_dir, ctx.run_dir, ctx.run_id, ctx.manifest_error) == (
        str(project),
        str(current),
        "registered_alias",
        None,
    )
    assert apply_location_defaults(command_input) == command_input


def test_explicit_workspace_overrides_current_workspace(location_project, monkeypatch):
    project, current, other = location_project
    monkeypatch.chdir(current)

    ctx = build_context(_input(workspace="other"))

    assert (ctx.project_dir, ctx.run_dir, ctx.run_id) == (str(project), str(other), "other")


def test_explicit_project_does_not_select_workspace_from_another_project(
    location_project, tmp_path, manifest_stubs, monkeypatch
):
    _project, current, _other = location_project
    selected = tmp_path / "selected"
    selected.mkdir()
    manifest_stubs.write(selected, [manifest_stubs.entry(selected, "selected_workspace")])
    monkeypatch.chdir(current)
    original = _input(project=str(selected))

    normalized = apply_location_defaults(original)
    ctx = build_context(original)

    assert normalized == original
    assert (ctx.project_dir, ctx.run_id, ctx.run_dir) == (
        str(selected),
        "selected_workspace",
        str(selected / "selected_workspace"),
    )


def test_explicit_relative_project_keeps_cwd_semantics(location_project, monkeypatch):
    project, current, _other = location_project
    monkeypatch.chdir(current)

    ctx = build_context(_input(project=".."))

    assert (ctx.project_dir, ctx.run_dir, ctx.run_id) == (
        str(project),
        str(current),
        "registered_alias",
    )


def test_external_workspace_can_be_inferred_with_explicit_project(
    location_project, tmp_path, manifest_stubs, monkeypatch
):
    project, current, _other = location_project
    external = tmp_path / "external"
    current.rename(external)
    entry = manifest_stubs.entry(project, "registered_alias")
    entry["workspace_path"] = str(external)
    manifest_stubs.write(project, [entry, manifest_stubs.entry(project, "other")])
    monkeypatch.chdir(external)

    ctx = build_context(_input(project=str(project)))

    assert (ctx.project_dir, ctx.run_dir, ctx.run_id) == (
        str(project),
        str(external),
        "registered_alias",
    )


def test_standalone_workspace_defaults_to_current_absolute_path(tmp_path, monkeypatch, capsys):
    current = tmp_path / "standalone"
    (current / "home").mkdir(parents=True)
    (current / "home" / "flow.json").write_text('{"steps":[]}')
    monkeypatch.chdir(current)

    assert cli_main.run(["status", "--json"]) == 0

    record = json.loads(capsys.readouterr().out)[0]
    assert record["workspace"] == str(current)
    assert not (tmp_path / "project.json").exists()


def test_arbitrary_project_subdirectory_is_not_assumed_to_be_workspace(
    location_project, monkeypatch
):
    project, _current, _other = location_project
    current = project / "not_a_workspace"
    current.mkdir()
    monkeypatch.chdir(current)

    assert apply_location_defaults(_input()) == _input()
    assert build_context(_input()).project_dir == str(current)


def test_missing_flow_still_selects_declared_workspace(location_project, monkeypatch):
    _project, current, _other = location_project
    (current / "home" / "flow.json").unlink()
    monkeypatch.chdir(current)

    assert build_context(_input()).run_id == "registered_alias"


def test_bad_parent_manifest_is_not_silently_bypassed(location_project, monkeypatch, capsys):
    project, current, _other = location_project
    (project / "project.json").write_text("{")
    monkeypatch.chdir(current)

    assert cli_main.run(["status", "--json"]) == 1

    assert json.loads(capsys.readouterr().out)[0]["error"] == "manifest_invalid"


def test_legacy_workspace_uses_exact_current_path(tmp_path, create_cli_project, monkeypatch):
    from pathlib import Path

    project = Path(create_cli_project())
    current = project / "runs" / "trial"
    (current / "home").mkdir(parents=True)
    (current / "home" / "flow.json").write_text('{"steps":[]}')
    monkeypatch.chdir(current)

    ctx = build_context(_input())

    assert (ctx.project_dir, ctx.run_dir, ctx.run_id) == (str(project), str(current), "trial")


@pytest.mark.parametrize(
    "arguments,handler",
    [
        (["run"], "chipcompiler.cli.command_handlers.project.run"),
        (["check"], "chipcompiler.cli.command_handlers.project.check"),
        (["status"], "chipcompiler.cli.command_handlers.inspect.status"),
        (["log"], "chipcompiler.cli.command_handlers.inspect.log"),
        (["config"], "chipcompiler.cli.command_handlers.inspect.config"),
        (["report", "qor"], "chipcompiler.cli.command_handlers.report.qor"),
        (["report", "step"], "chipcompiler.cli.command_handlers.report.step"),
        (["signoff", "inspect"], "chipcompiler.cli.command_handlers.signoff.inspect"),
        (["param", "show", "cts.max_fanout"], "chipcompiler.cli.commands.param.param_show_handler"),
        (
            ["param", "set", "cts.max_fanout", "12"],
            "chipcompiler.cli.commands.param.param_set_handler",
        ),
        (
            ["param", "unset", "cts.max_fanout"],
            "chipcompiler.cli.commands.param.param_unset_handler",
        ),
        (["param", "diff"], "chipcompiler.cli.commands.param.param_diff_handler"),
    ],
)
def test_workspace_defaults_are_passed_to_handlers(
    location_project, monkeypatch, capsys, arguments, handler
):
    project, current, _other = location_project
    monkeypatch.chdir(current)
    seen = []

    def fake(command_input, ctx):
        seen.append((command_input.project.project, command_input.workspace, ctx.run_dir))
        return CommandResult.ok([])

    monkeypatch.setattr(handler, fake)

    assert cli_main.run([*arguments, "--plain"]) == 0

    assert seen == [(str(project), "registered_alias", str(current))]
    assert capsys.readouterr().err == ""


def test_parameter_list_selects_workspace_renderer_after_inference(
    location_project, monkeypatch, capsys, plain_records
):
    _project, current, _other = location_project
    monkeypatch.chdir(current)
    seen = []

    def fake(command_input, ctx):
        seen.append(command_input.workspace)
        return CommandResult.ok([{"record": "parameter", "current": True}])

    monkeypatch.setattr("chipcompiler.cli.commands.param.param_list_handler", fake)

    assert cli_main.run(["param", "list", "--all", "--plain"]) == 0

    assert plain_records(capsys.readouterr().out) == [{"record": "parameter", "current": "true"}]
    assert seen == ["registered_alias"]


@pytest.mark.parametrize("command", ["inspect", "cancel", "reconcile"])
def test_process_workspace_option_can_default_to_current_workspace(
    location_project, monkeypatch, capsys, command
):
    project, current, _other = location_project
    monkeypatch.chdir(current)
    seen = []
    options = ["--run-id", "12345678-1234-1234-1234-123456789abc"] if command == "cancel" else []

    def fake(*args, **kwargs):
        seen.append(args[:2])
        return () if command == "reconcile" else {"run_id": "saved-id", "pid": 123}

    monkeypatch.setattr(f"chipcompiler.project.process_control.{command}_process", fake)

    assert cli_main.run(["process", command, *options, "--plain"]) == 0

    assert seen == [(str(project), "registered_alias")]
    assert capsys.readouterr().err == ""


def test_process_omission_outside_workspace_remains_an_error(
    location_project, monkeypatch, capsys, plain_records
):
    project, _current, _other = location_project
    monkeypatch.chdir(project)

    assert cli_main.run(["process", "inspect", "--plain"]) == 1

    assert plain_records(capsys.readouterr().out)[0]["error"] == "workspace_required"


def test_explicit_project_and_workspace_are_not_changed(location_project, monkeypatch):
    project, current, _other = location_project
    monkeypatch.chdir(current)
    original = _input(project=str(project), workspace="other")

    assert apply_location_defaults(original) is original
    assert build_context(original).run_id == "other"


def test_project_report_from_workspace_uses_owning_project(location_project, monkeypatch, capsys):
    project, current, _other = location_project
    monkeypatch.chdir(current)

    assert cli_main.run(["report", "project", "--json"]) == 0

    report = json.loads(capsys.readouterr().out)[0]
    assert report["project"] == str(project)
    assert [row["workspace_id"] for row in report["workspaces"]] == ["registered_alias", "other"]


@pytest.mark.parametrize("selector", ["registered_alias", "physical_directory"])
def test_explicit_workspace_spelling_is_not_replaced_by_current_alias(
    location_project, monkeypatch, selector
):
    project, current, _other = location_project
    monkeypatch.chdir(current)

    command_input = apply_location_defaults(_input(project=str(project), workspace=selector))

    assert command_input.workspace == selector


def test_process_absolute_selector_uses_registered_id(location_project, monkeypatch, capsys):
    project, current, _other = location_project
    seen = []

    def fake(project_dir, workspace_id, run_id):
        seen.append((project_dir, workspace_id))
        return {"run_id": "saved-id", "pid": 123}

    monkeypatch.setattr("chipcompiler.project.process_control.inspect_process", fake)

    assert (
        cli_main.run(
            [
                "process",
                "inspect",
                "--project",
                str(project),
                "--workspace",
                str(current),
                "--plain",
            ]
        )
        == 0
    )

    assert seen == [(str(project), "registered_alias")]
    assert capsys.readouterr().err == ""


def test_init_keeps_its_original_current_directory_semantics(location_project, monkeypatch, capsys):
    _project, current, _other = location_project
    monkeypatch.chdir(current)
    seen = []

    def fake(command_input, ctx):
        seen.append(ctx.project_dir)
        return CommandResult.ok([])

    monkeypatch.setattr("chipcompiler.cli.command_handlers.project.init", fake)

    assert cli_main.run(["init", "new_project", "--plain"]) == 0

    assert seen == [str(current)]
    assert capsys.readouterr().err == ""
