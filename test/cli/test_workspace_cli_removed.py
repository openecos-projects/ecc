from pathlib import Path

from chipcompiler.cli import main as cli_main


def test_workspace_command_exposes_refresh_only(capsys):
    rc = cli_main.run(["workspace", "--help"])

    assert rc == 0
    assert "refresh" in capsys.readouterr().out


def test_legacy_workspace_subcommands_are_not_forwarded(capsys):
    for args in (
        ["workspace", "create", "--json"],
        ["workspace", "run-flow", "--json"],
        ["workspace", "run-step", "--json"],
    ):
        rc = cli_main.run(args)

        assert rc != 0
        assert "No such command" in capsys.readouterr().err


def test_current_docs_do_not_advertise_removed_workspace_subcommands():
    docs = [
        Path("docs/workspace-cli.md"),
        Path("docs/specification/cli-design.md"),
    ]
    forbidden = ["ecc workspace create", "ecc workspace run-flow", "ecc workspace run-step"]

    for path in docs:
        source = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in source, f"{path} still contains {marker}"
