from chipcompiler.cli import main as cli_main


def test_show_completion_prints_zsh_script(monkeypatch, capsys):
    monkeypatch.setenv("_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION", "1")

    rc = cli_main.run(["--show-completion", "zsh"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "#compdef ecc" in out
    assert "_ECC_COMPLETE=complete_zsh" in out


def test_show_completion_prints_bash_script(monkeypatch, capsys):
    monkeypatch.setenv("_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION", "1")

    rc = cli_main.run(["--show-completion", "bash"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "complete -o default -F _ecc_completion ecc" in out
    assert "_ECC_COMPLETE=complete_bash" in out


def test_completion_request_with_empty_argv_returns_candidates(monkeypatch, capsys):
    monkeypatch.setenv("_ECC_COMPLETE", "complete_bash")
    monkeypatch.setenv("COMP_WORDS", "ecc vers")
    monkeypatch.setenv("COMP_CWORD", "1")

    rc = cli_main.run([])

    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip() == "version"


def test_empty_argv_without_completion_env_still_shows_help(monkeypatch, capsys):
    monkeypatch.delenv("_ECC_COMPLETE", raising=False)

    rc = cli_main.run([])

    out = capsys.readouterr()
    assert rc == 1
    assert "Commands" in out.out + out.err
