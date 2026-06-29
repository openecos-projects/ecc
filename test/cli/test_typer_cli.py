import dataclasses
import json
from importlib import metadata

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
        "metrics",
        "artifacts",
        "config",
        "diagnose",
        "param",
        "workspace",
    ):
        assert command in out


def test_root_version_returns_single_line(capsys):
    rc = cli_main.run(["--version"])

    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("ecc ")
    assert out.endswith("\n")
    assert len(out.splitlines()) == 1


def test_version_command_returns_stable_text_lines(capsys):
    rc = cli_main.run(["version"])

    lines = capsys.readouterr().out.splitlines()
    assert rc == 0
    assert len(lines) == 4
    assert lines[0].startswith("ecc ")
    assert lines[1].startswith("dreamplace ")
    assert lines[2].startswith("ecc_tools ")
    assert lines[3] == "runtime ECC CLI"


def test_version_command_returns_json_payload(capsys):
    rc = cli_main.run(["version", "--json"])

    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert set(data) == {"schema_version", "runtime", "ecc", "dreamplace", "ecc_tools"}
    assert data["schema_version"] == 1
    assert data["runtime"] == "ECC CLI"


def test_version_metadata_missing_uses_unknown(monkeypatch, capsys):
    def missing_version(distribution):
        raise metadata.PackageNotFoundError(distribution)

    monkeypatch.setattr("chipcompiler.cli.core.version_info.metadata.version", missing_version)
    monkeypatch.setattr("chipcompiler.__version__", "source-fallback")

    rc = cli_main.run(["version", "--json"])

    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data == {
        "schema_version": 1,
        "runtime": "ECC CLI",
        "ecc": "source-fallback",
        "dreamplace": "unknown",
        "ecc_tools": "unknown",
    }


def test_param_help_returns_zero_and_lists_subcommands(capsys):
    rc = cli_main.run(["param", "--help"])

    out = capsys.readouterr().out
    assert rc == 0
    for command in ("list", "show", "set", "unset", "diff"):
        assert command in out


def test_workspace_help_returns_zero_and_lists_subcommands(capsys):
    rc = cli_main.run(["workspace", "--help"])

    out = capsys.readouterr().out
    assert rc == 0
    for command in ("create", "load", "run-flow", "run-step", "get-info", "get-home"):
        assert command in out


def test_unknown_command_returns_nonzero_without_system_exit(capsys):
    rc = cli_main.run(["missing-command"])

    assert rc != 0
    assert "No such command" in capsys.readouterr().err


def test_invalid_option_returns_nonzero_without_system_exit(capsys):
    rc = cli_main.run(["status", "--missing-option"])

    assert rc != 0
    assert "No such option" in capsys.readouterr().err


def test_config_requires_resolved_without_system_exit(tmp_path, capsys):
    project = tmp_path / "project"
    project.mkdir()

    rc = cli_main.run(["config", "--project", str(project)])

    assert rc != 0
    assert "--resolved" in capsys.readouterr().err


def test_output_mode_priority_prefers_jsonl(monkeypatch, tmp_path, capsys):
    seen = {}

    def fake_resolve_project_dir(project):
        return str(tmp_path)

    def fake_resolve_run_dir(project_dir, run_id):
        return (str(tmp_path / "runs" / "default"), run_id)

    def fake_status(command_input, ctx):
        seen["input_type"] = type(command_input).__name__
        seen["frozen"] = dataclasses.is_dataclass(command_input)
        seen["mode"] = ctx.output_mode.value
        seen["json"] = command_input.output.json
        seen["jsonl"] = command_input.output.jsonl
        seen["plain"] = command_input.output.plain
        return CommandResult.ok([{"status": "ok"}])

    monkeypatch.setattr(
        "chipcompiler.cli.core.invocation.resolve_project_dir",
        fake_resolve_project_dir,
    )
    monkeypatch.setattr("chipcompiler.cli.core.invocation.resolve_run_dir", fake_resolve_run_dir)
    monkeypatch.setattr("chipcompiler.cli.command_handlers.inspect.status", fake_status)

    rc = cli_main.run(["status", "--jsonl", "--json", "--plain"])

    objects = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert rc == 0
    assert objects == [{"status": "ok"}]
    assert seen == {
        "input_type": "StatusInput",
        "frozen": True,
        "mode": "jsonl",
        "json": True,
        "jsonl": True,
        "plain": True,
    }


def test_run_set_remains_repeatable(monkeypatch, tmp_path):
    seen = {}

    monkeypatch.setattr(
        "chipcompiler.cli.core.invocation.resolve_project_dir",
        lambda project: str(tmp_path),
    )
    monkeypatch.setattr(
        "chipcompiler.cli.core.invocation.resolve_run_dir",
        lambda project_dir, run_id: (str(tmp_path / "runs" / "default"), run_id),
    )

    def fake_run(command_input, ctx):
        seen["input_type"] = type(command_input).__name__
        seen["param_set"] = command_input.param_set
        return CommandResult.ok([{"status": "ok"}])

    monkeypatch.setattr("chipcompiler.cli.command_handlers.project.run", fake_run)

    rc = cli_main.run(["run", "--set", "place.target_density=0.65", "--set", "synth.max_fanout=16"])

    assert rc == 0
    assert seen == {
        "input_type": "RunInput",
        "param_set": ("place.target_density=0.65", "synth.max_fanout=16"),
    }


def test_workspace_routes_through_root_typer(monkeypatch):
    seen = {}

    def fake_invoke(argv, *, keep_workspace_json_stdio_redirect=False):
        seen["argv"] = argv
        seen["keep_workspace_json_stdio_redirect"] = keep_workspace_json_stdio_redirect
        return 17

    monkeypatch.setattr("chipcompiler.cli.app.invoke_typer_app", fake_invoke)

    rc = cli_main.run(["workspace", "create", "--pdk-root", "/pdk"])

    assert rc == 17
    assert seen["argv"] == ["workspace", "create", "--pdk-root", "/pdk"]
    assert seen["keep_workspace_json_stdio_redirect"] is False


def test_run_default_argv_keeps_programmatic_stdio_redirect_disabled(monkeypatch):
    seen = {}

    def fake_invoke(argv, *, keep_workspace_json_stdio_redirect=False):
        seen["argv"] = argv
        seen["keep_workspace_json_stdio_redirect"] = keep_workspace_json_stdio_redirect
        return 17

    monkeypatch.setattr(cli_main.sys, "argv", ["ecc", "workspace", "load", "--json"])
    monkeypatch.setattr("chipcompiler.cli.app.invoke_typer_app", fake_invoke)

    rc = cli_main.run()

    assert rc == 17
    assert seen["argv"] == ["workspace", "load", "--json"]
    assert seen["keep_workspace_json_stdio_redirect"] is False


def test_main_enables_cli_stdio_redirect(monkeypatch):
    seen = {}

    def fake_invoke(argv, *, keep_workspace_json_stdio_redirect=False):
        seen["argv"] = argv
        seen["keep_workspace_json_stdio_redirect"] = keep_workspace_json_stdio_redirect
        return 17

    monkeypatch.setattr(cli_main.sys, "argv", ["ecc", "workspace", "load", "--json"])
    monkeypatch.setattr("chipcompiler.cli.app.invoke_typer_app", fake_invoke)

    try:
        cli_main.main()
    except SystemExit as exc:
        code = exc.code
    else:
        raise AssertionError("main() did not exit")

    assert code == 17
    assert seen["argv"] == ["workspace", "load", "--json"]
    assert seen["keep_workspace_json_stdio_redirect"] is True


def test_old_top_level_workspace_form_is_root_parser_error(capsys):
    rc = cli_main.run(["--workspace", "gcd", "--rtl", "gcd.v"])

    assert rc != 0
    assert "no such option" in capsys.readouterr().err.lower()


def test_run_workspace_like_flag_is_run_parser_error(capsys):
    rc = cli_main.run(["run", "--workspace", "gcd"])

    assert rc != 0
    assert "no such option" in capsys.readouterr().err.lower()


def test_non_workspace_command_handler_still_returns_command_result(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        "chipcompiler.cli.core.invocation.resolve_project_dir",
        lambda project: str(tmp_path),
    )
    monkeypatch.setattr(
        "chipcompiler.cli.core.invocation.resolve_run_dir",
        lambda project_dir, run_id: (str(tmp_path / "runs" / "default"), run_id),
    )

    def fake_diagnose(command_input, ctx):
        return CommandResult.ok(
            [
                {"command": "diagnose", "input_type": type(command_input).__name__, "status": "ok"},
            ]
        )

    monkeypatch.setattr(
        "chipcompiler.cli.command_handlers.inspect.diagnose",
        fake_diagnose,
    )

    rc = cli_main.run(["diagnose", "--json"])

    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data == {
        "records": [{"command": "diagnose", "input_type": "DiagnoseInput", "status": "ok"}],
    }


def test_param_callback_passes_typed_input(monkeypatch, tmp_path, capsys):
    seen = {}
    monkeypatch.setattr(
        "chipcompiler.cli.core.invocation.resolve_project_dir",
        lambda project: str(tmp_path),
    )
    monkeypatch.setattr(
        "chipcompiler.cli.core.invocation.resolve_run_dir",
        lambda project_dir, run_id: (str(tmp_path / "runs" / "default"), run_id),
    )

    def fake_show(command_input, ctx):
        seen["input_type"] = type(command_input).__name__
        seen["key"] = command_input.key
        seen["project"] = command_input.project.project
        return CommandResult.ok([{"param": command_input.key}])

    monkeypatch.setattr("chipcompiler.cli.commands.param.param_show_handler", fake_show)

    rc = cli_main.run(["param", "show", "place.target_density", "--project", "gcd", "--json"])

    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"records": [{"param": "place.target_density"}]}
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

    def fake_resolve_run_dir(project_dir, run_id):
        return (str(tmp_path / "runs" / "default"), run_id)

    def fake_handler(command_input, ctx):
        return CommandResult.ok([{"status": "ok"}])

    def fake_renderer(result, ctx, command_input, color):
        print(f"registry:{ctx.output_mode.value}:{result.records[0]['status']}")

    monkeypatch.setattr(
        "chipcompiler.cli.core.invocation.resolve_project_dir",
        fake_resolve_project_dir,
    )
    monkeypatch.setattr("chipcompiler.cli.core.invocation.resolve_run_dir", fake_resolve_run_dir)
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
