import pytest
import typer

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.app import app


def _walk(command, path):
    yield path
    for name, sub in sorted(getattr(command, "commands", {}).items()):
        yield from _walk(sub, [*path, name])


def _all_command_paths():
    return list(_walk(typer.main.get_command(app), []))


@pytest.mark.parametrize("path", _all_command_paths(), ids=lambda path: " ".join(path) or "ecc")
def test_help_renders_for_every_command(path, capsys):
    rc = cli_main.run([*path, "--help"])

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out
    assert not captured.err
    assert "\x1b[" not in captured.out


def test_root_command_list_keeps_one_line_summaries(capsys):
    rc = cli_main.run(["--help"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "Run the configured RTL-to-GDS flow" in out
    assert "Show resolved project or step configuration" in out


def test_param_command_list_keeps_one_line_summaries(capsys):
    rc = cli_main.run(["param", "--help"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "List parameter overrides" in out
    assert "Show one parameter value" in out
    assert "Set a parameter override" in out
    assert "Remove a parameter override" in out
    assert "Compare parameter overrides with defaults" in out


def test_workspace_refresh_summary_unchanged(capsys):
    rc = cli_main.run(["workspace", "--help"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "Recreate a workspace from ecc.toml without running it" in out


def test_pdk_set_root_summary_unchanged(capsys):
    rc = cli_main.run(["pdk", "--help"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "Set the [pdk] root path in ecc.toml" in out


def test_option_help_preserves_angle_bracket_placeholder(capsys):
    rc = cli_main.run(["report", "qor", "--help"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "<workspace>/signoff/" in out
