import json
from types import SimpleNamespace

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


def test_legacy_workspace_routes_before_root_typer(monkeypatch):
    seen = {}

    def fake_run_legacy(argv):
        seen["argv"] = argv
        return 17

    monkeypatch.setattr("chipcompiler.cli.workspace_legacy.run_legacy_workspace", fake_run_legacy)

    rc = cli_main.run(["--workspace", "gcd", "--rtl", "gcd.v"])

    assert rc == 17
    assert seen["argv"] == ["--workspace", "gcd", "--rtl", "gcd.v"]


def test_explicit_workspace_is_not_legacy(monkeypatch):
    seen = {}

    def fake_workspace_app(argv):
        seen["argv"] = argv
        return 19

    monkeypatch.setattr("chipcompiler.cli.workspace_app.run_workspace_app", fake_workspace_app)
    monkeypatch.setattr(
        "chipcompiler.cli.workspace_legacy.run_legacy_workspace",
        lambda argv: (_ for _ in ()).throw(AssertionError("legacy path should not run")),
    )

    rc = cli_main.run(["workspace", "create", "--pdk-root", "/pdk"])

    assert rc == 19
    assert seen["argv"] == ["create", "--pdk-root", "/pdk"]


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


def test_legacy_filelist_like_rtl_routes_to_input_filelist(monkeypatch, tmp_path):
    from chipcompiler.cli.workspace_legacy import run_legacy_workspace

    rtl = tmp_path / "rtl.f"
    rtl.write_text("gcd.v\n")
    pdk_root = tmp_path / "pdk"
    pdk_root.mkdir()
    capture = {}

    class DummyFlow:
        def __init__(self, workspace):
            self.workspace = workspace

        def has_init(self):
            return True

        def create_step_workspaces(self):
            pass

        def run_steps(self):
            return True

    def fake_create_workspace(**kwargs):
        capture["kwargs"] = kwargs
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(
        "chipcompiler.data.get_parameters",
        lambda pdk: SimpleNamespace(data={}),
    )
    monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create_workspace)
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", DummyFlow)

    rc = run_legacy_workspace(
        [
            "--workspace",
            str(tmp_path / "ws"),
            "--rtl",
            str(rtl),
            "--design",
            "gcd",
            "--top",
            "gcd",
            "--clock",
            "clk",
            "--pdk-root",
            str(pdk_root),
        ],
    )

    assert rc == 0
    assert capture["kwargs"]["origin_verilog"] == ""
    assert capture["kwargs"]["input_filelist"] == str(rtl)
