from chipcompiler.cli import main as cli_main


def test_workspace_command_is_not_registered(capsys):
    rc = cli_main.run(["workspace", "--help"])

    assert rc != 0
    assert "No such command 'workspace'" in capsys.readouterr().err


def test_workspace_compatibility_subcommands_are_not_forwarded(capsys):
    for args in (
        ["workspace", "create", "--json"],
        ["workspace", "run-flow", "--json"],
        ["workspace", "run-step", "--json"],
    ):
        rc = cli_main.run(args)

        assert rc != 0
        assert "No such command 'workspace'" in capsys.readouterr().err
