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


def test_help_keeps_styles_when_color_is_forced(monkeypatch, capsys):
    monkeypatch.setattr("typer.rich_utils.FORCE_TERMINAL", True)

    rc = cli_main.run(["--help"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "\x1b[" in captured.out
    assert not captured.err


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


def test_param_set_help_documents_scopes_and_value_parsing(capsys):
    rc = cli_main.run(["param", "set", "--help"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "ecc.toml" in out
    assert "params.toml" in out
    assert "'[4, 5]'" in out
    assert "skew_bound" in out
    assert "max_buf_tran" in out
    assert "invalid_value" in out


def test_param_set_help_wraps_at_narrow_width(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "50")

    rc = cli_main.run(["param", "set", "--help"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "…" not in out
    for token in ("pdk.overrides", "params.toml", "workspace NAME"):
        assert token in out


def test_run_help_documents_fresh_run_override_rule(capsys):
    rc = cli_main.run(["run", "--help"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "set_requires_fresh_run" in out
    assert "cli-param-overrides.json" in out


def test_workspace_refresh_help_warns_about_manual_edits(capsys):
    rc = cli_main.run(["workspace", "refresh", "--help"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "overwritten" in out


def test_config_help_names_steps_without_step_specific_config(capsys):
    rc = cli_main.run(["config", "--help"])

    out = capsys.readouterr().out
    assert rc == 0
    for step in ("lec", "lvs", "postroutelec", "harden"):
        assert step in out


def test_pdk_set_root_help_documents_path_resolution(capsys):
    rc = cli_main.run(["pdk", "set-root", "--help"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "pdk.sdc" in out
    assert "pdk.spef" in out
    assert "project directory" in out


@pytest.mark.parametrize(
    "path",
    [
        ["param", "list"],
        ["param", "show"],
        ["param", "set"],
        ["param", "unset"],
        ["param", "diff"],
        ["run"],
        ["config"],
        ["workspace", "refresh"],
        ["pdk", "set-root"],
    ],
    ids=lambda path: " ".join(path),
)
def test_enriched_help_points_to_doc_config(path, capsys):
    rc = cli_main.run([*path, "--help"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "ecc doc config" in out
