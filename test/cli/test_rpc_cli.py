from chipcompiler.cli import main as cli_main


def test_rpc_help_returns_zero_and_lists_serve(capsys):
    rc = cli_main.run(["rpc", "--help"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "serve" in out


def test_rpc_serve_help_returns_zero_and_lists_stdio(capsys):
    rc = cli_main.run(["rpc", "serve", "--help"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "--stdio" in out


def test_rpc_serve_requires_stdio(capsys):
    rc = cli_main.run(["rpc", "serve"])

    assert rc != 0
    assert "--stdio" in capsys.readouterr().err
