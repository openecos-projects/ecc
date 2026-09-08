import json
import re
from importlib import metadata

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.core.inputs import OutputOptions, ProjectOptions
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.types import CommandResult


def test_root_help_returns_zero_and_lists_commands(capsys):
    rc = cli_main.run(["--help"])

    out = capsys.readouterr().out
    assert rc == 0
    for command in (
        "init",
        "check",
        "run",
        "status",
        "log",
        "config",
        "doctor",
        "param",
        "pdk",
        "project",
        "workspace",
        "signoff",
        "report",
    ):
        assert command in out
    for removed_command in ("metrics", "artifacts", "diagnose"):
        assert removed_command not in out


def test_root_help_lists_doc_right_after_version(capsys):
    rc = cli_main.run(["--help"])

    out = capsys.readouterr().out
    assert rc == 0
    # Command rows look like "│ <name>   <help>"; wrapped help lines start
    # with whitespace after the border and never match this pattern.
    order = [
        match.group(1)
        for line in out.splitlines()
        if (match := re.match(r"^│ (\w[\w-]*)  +\S", line))
    ]
    assert order[:3] == ["version", "doc", "layout-image"]


def test_root_version_returns_single_line(capsys):
    rc = cli_main.run(["--version"])

    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("ecc ")
    assert out.endswith("\n")
    assert len(out.splitlines()) == 1


def test_version_command_returns_stable_text_lines(monkeypatch, capsys):
    monkeypatch.setattr(
        "chipcompiler.cli.app.tool_versions",
        lambda: {"yosys": "0.68", "sizer": "not installed", "klayout": "0.30.2"},
    )

    rc = cli_main.run(["version"])

    lines = capsys.readouterr().out.splitlines()
    assert rc == 0
    assert len(lines) == 7
    assert lines[0].startswith("ecc ")
    assert lines[1].startswith("dreamplace ")
    assert lines[2].startswith("ecc_tools ")
    assert lines[3] == "runtime ECC CLI"
    assert lines[4] == "yosys 0.68"
    assert lines[5] == "sizer not installed"
    assert lines[6] == "klayout 0.30.2"


def test_version_command_returns_json_payload(monkeypatch, capsys):
    monkeypatch.setattr(
        "chipcompiler.cli.app.tool_versions",
        lambda: {"yosys": "0.68", "sizer": "unknown", "klayout": "not installed"},
    )

    rc = cli_main.run(["version", "--json"])

    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert set(data) == {"schema_version", "runtime", "ecc", "dreamplace", "ecc_tools", "tools"}
    assert data["schema_version"] == 1
    assert data["runtime"] == "ECC CLI"
    assert data["tools"] == {"yosys": "0.68", "sizer": "unknown", "klayout": "not installed"}


def test_version_metadata_missing_uses_unknown(monkeypatch, capsys):
    def missing_version(distribution):
        raise metadata.PackageNotFoundError(distribution)

    monkeypatch.setattr("chipcompiler.cli.core.version_info.metadata.version", missing_version)
    monkeypatch.setattr("chipcompiler.__version__", "source-fallback")
    monkeypatch.setattr(
        "chipcompiler.cli.app.tool_versions",
        lambda: {"yosys": "0.68", "sizer": "unknown", "klayout": "not installed"},
    )

    rc = cli_main.run(["version", "--json"])

    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data == {
        "schema_version": 1,
        "runtime": "ECC CLI",
        "ecc": "source-fallback",
        "dreamplace": "unknown",
        "ecc_tools": "unknown",
        "tools": {"yosys": "0.68", "sizer": "unknown", "klayout": "not installed"},
    }


def test_param_help_returns_zero_and_lists_subcommands(capsys):
    rc = cli_main.run(["param", "--help"])

    out = capsys.readouterr().out
    assert rc == 0
    for command in ("list", "show", "set", "unset", "diff"):
        assert command in out


def test_unknown_command_returns_nonzero_without_system_exit(capsys):
    rc = cli_main.run(["missing-command"])

    assert rc != 0
    assert "No such command" in capsys.readouterr().err


@pytest.mark.parametrize("command", ("metrics", "artifacts", "diagnose"))
def test_removed_commands_return_unknown_command(command, capsys):
    rc = cli_main.run([command])

    assert rc != 0
    assert "No such command" in capsys.readouterr().err


def test_invalid_option_returns_nonzero_without_system_exit(capsys):
    rc = cli_main.run(["status", "--missing-option"])

    assert rc != 0
    assert "No such option" in capsys.readouterr().err


def test_config_without_resolved_reaches_the_config_handler(tmp_path, capsys, plain_records):
    project = tmp_path / "project"
    project.mkdir()

    rc = cli_main.run(["config", "--project", str(project), "--plain"])

    assert rc == 1
    assert plain_records(capsys.readouterr().out)[0]["error"] == "missing_config"


def test_removed_config_resolved_option_returns_unknown_option(capsys):
    rc = cli_main.run(["config", "--resolved"])

    assert rc != 0
    assert "No such option" in capsys.readouterr().err


def test_removed_log_errors_option_returns_unknown_option(capsys):
    rc = cli_main.run(["log", "synthesis", "--errors"])

    assert rc != 0
    assert "No such option" in capsys.readouterr().err


def test_removed_signoff_report_command_returns_unknown_command(capsys):
    rc = cli_main.run(["signoff", "report"])

    assert rc != 0
    assert "No such command" in capsys.readouterr().err


def test_run_set_remains_repeatable(monkeypatch, tmp_path):
    seen = {}

    monkeypatch.setattr(
        "chipcompiler.cli.core.invocation.resolve_project_dir",
        lambda project: str(tmp_path),
    )

    def fake_run(command_input, ctx):
        seen["input_type"] = type(command_input).__name__
        seen["param_set"] = command_input.param_set
        return CommandResult.ok([{"status": "ok"}])

    monkeypatch.setattr("chipcompiler.cli.command_handlers.project.run", fake_run)

    rc = cli_main.run(["run", "--set", "place.target_density=0.65", "--set", "cts.max_fanout=16"])

    assert rc == 0
    assert seen == {
        "input_type": "RunInput",
        "param_set": ("place.target_density=0.65", "cts.max_fanout=16"),
    }


def test_removed_rpc_command_returns_unknown_command(capsys):
    rc = cli_main.run(["rpc", "serve", "--stdio"])

    assert rc != 0
    assert "No such command" in capsys.readouterr().err


def test_run_default_argv_uses_sys_argv(monkeypatch):
    seen = {}

    def fake_invoke(argv):
        seen["argv"] = argv
        return 17

    monkeypatch.setattr(cli_main.sys, "argv", ["ecc", "status"])
    monkeypatch.setattr("chipcompiler.cli.app.invoke_typer_app", fake_invoke)

    rc = cli_main.run()

    assert rc == 17
    assert seen["argv"] == ["status"]


def test_main_exits_with_run_code(monkeypatch):
    seen = {}

    def fake_invoke(argv):
        seen["argv"] = argv
        return 17

    monkeypatch.setattr(cli_main.sys, "argv", ["ecc", "status"])
    monkeypatch.setattr("chipcompiler.cli.app.invoke_typer_app", fake_invoke)

    try:
        cli_main.main()
    except SystemExit as exc:
        code = exc.code
    else:
        raise AssertionError("main() did not exit")

    assert code == 17
    assert seen["argv"] == ["status"]


def test_old_top_level_workspace_form_is_root_parser_error(capsys):
    rc = cli_main.run(["--workspace", "gcd", "--rtl", "gcd.v"])

    assert rc != 0
    assert "no such option" in capsys.readouterr().err.lower()


def test_run_workspace_flag_reaches_workspace_validation(capsys):
    rc = cli_main.run(["run", "--workspace", "gcd/rtl"])

    assert rc != 0
    assert "invalid_workspace" in capsys.readouterr().out


def test_status_command_handler_still_returns_command_result(
    monkeypatch, tmp_path, capsys, plain_records
):
    monkeypatch.setattr(
        "chipcompiler.cli.core.invocation.resolve_project_dir",
        lambda project: str(tmp_path),
    )

    def fake_status(command_input, ctx):
        return CommandResult.ok([{"command": "status", "status": "ok"}])

    monkeypatch.setattr("chipcompiler.cli.command_handlers.inspect.status", fake_status)

    rc = cli_main.run(["status", "--plain"])

    assert rc == 0
    assert plain_records(capsys.readouterr().out) == [{"command": "status", "status": "ok"}]


def test_param_callback_passes_typed_input(monkeypatch, tmp_path, capsys, plain_records):
    seen = {}
    monkeypatch.setattr(
        "chipcompiler.cli.core.invocation.resolve_project_dir",
        lambda project: str(tmp_path),
    )

    def fake_show(command_input, ctx):
        seen["input_type"] = type(command_input).__name__
        seen["key"] = command_input.key
        seen["project"] = command_input.project.project
        return CommandResult.ok([{"param": command_input.key}])

    monkeypatch.setattr("chipcompiler.cli.commands.param.param_show_handler", fake_show)

    rc = cli_main.run(["param", "show", "place.target_density", "--project", "gcd", "--plain"])

    assert rc == 0
    assert plain_records(capsys.readouterr().out) == [{"param": "place.target_density"}]
    assert seen == {
        "input_type": "ParamShowInput",
        "key": "place.target_density",
        "project": "gcd",
    }


def test_execute_command_uses_renderer_registry(monkeypatch, tmp_path, capsys):
    from dataclasses import dataclass

    import click

    from chipcompiler.cli.core.types import OutputMode

    @dataclass(frozen=True)
    class DummyInput:
        output: OutputOptions
        project: ProjectOptions

    def fake_resolve_project_dir(project):
        return str(tmp_path)

    def fake_handler(command_input, ctx):
        return CommandResult.ok([{"status": "ok"}])

    def fake_renderer(result, ctx, command_input, color):
        print(f"registry:{ctx.output_mode.value}:{result.records[0]['status']}")

    monkeypatch.setattr(
        "chipcompiler.cli.core.invocation.resolve_project_dir",
        fake_resolve_project_dir,
    )
    monkeypatch.setitem(
        __import__("chipcompiler.cli.rendering.renderers", fromlist=["RENDERERS"]).RENDERERS,
        ("custom", OutputMode.TEXT),
        fake_renderer,
    )

    rc = cli_main.run(["status", "--help"])
    assert rc == 0
    capsys.readouterr()

    try:
        execute_command(
            "status",
            DummyInput(output=OutputOptions(), project=ProjectOptions()),
            fake_handler,
            render_key="custom",
        )
    except click.exceptions.Exit as exc:
        assert exc.exit_code == 0

    assert capsys.readouterr().out.strip() == "registry:text:ok"


class TestEdgeCases:
    def test_no_command_returns_nonzero(self, capsys):
        rc = cli_main.run([])
        assert rc == 1
