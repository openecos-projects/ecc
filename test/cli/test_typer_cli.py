import json

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.types import CommandResult


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

    def fake_dispatch(args, ctx):
        seen["mode"] = ctx.output_mode.value
        seen["json"] = args.json
        seen["jsonl"] = args.jsonl
        seen["plain"] = args.plain
        return CommandResult.ok([{"status": "ok"}])

    monkeypatch.setattr("chipcompiler.cli.commands.resolve_project_dir", fake_resolve_project_dir)
    monkeypatch.setattr("chipcompiler.cli.commands.resolve_run_dir", fake_resolve_run_dir)
    monkeypatch.setattr("chipcompiler.cli.invocation.dispatch", fake_dispatch)

    rc = cli_main.run(["status", "--jsonl", "--json", "--plain"])

    objects = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert rc == 0
    assert objects == [{"status": "ok"}]
    assert seen == {"mode": "jsonl", "json": True, "jsonl": True, "plain": True}


def test_run_set_remains_repeatable(monkeypatch, tmp_path):
    seen = {}

    monkeypatch.setattr(
        "chipcompiler.cli.commands.resolve_project_dir",
        lambda project: str(tmp_path),
    )
    monkeypatch.setattr(
        "chipcompiler.cli.commands.resolve_run_dir",
        lambda project_dir, run_id: (str(tmp_path / "runs" / "default"), run_id),
    )

    def fake_dispatch(args, ctx):
        seen["param_set"] = args.param_set
        return CommandResult.ok([{"status": "ok"}])

    monkeypatch.setattr("chipcompiler.cli.invocation.dispatch", fake_dispatch)

    rc = cli_main.run(["run", "--set", "place.target_density=0.65", "--set", "synth.max_fanout=16"])

    assert rc == 0
    assert seen["param_set"] == ["place.target_density=0.65", "synth.max_fanout=16"]


def test_workspace_routes_through_root_typer(monkeypatch):
    seen = {}

    def fake_invoke(argv):
        seen["argv"] = argv
        return 17

    monkeypatch.setattr("chipcompiler.cli.app.invoke_typer_app", fake_invoke)

    rc = cli_main.run(["workspace", "create", "--pdk-root", "/pdk"])

    assert rc == 17
    assert seen["argv"] == ["workspace", "create", "--pdk-root", "/pdk"]


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
        "chipcompiler.cli.commands.resolve_project_dir",
        lambda project: str(tmp_path),
    )
    monkeypatch.setattr(
        "chipcompiler.cli.commands.resolve_run_dir",
        lambda project_dir, run_id: (str(tmp_path / "runs" / "default"), run_id),
    )
    monkeypatch.setattr(
        "chipcompiler.cli.invocation.dispatch",
        lambda args, ctx: CommandResult.ok([{"command": args.command, "status": "ok"}]),
    )

    rc = cli_main.run(["diagnose", "--json"])

    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data == {"records": [{"command": "diagnose", "status": "ok"}]}
