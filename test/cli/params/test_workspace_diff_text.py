"""``ecc param diff --workspace`` in the default text mode."""

from pathlib import Path

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.rendering.pretty import render_param_diff_text
from test.cli.params.test_workspace_commands import _Flow, _workspace, _write_manifest


def _project_with_workspace(create_cli_project, monkeypatch) -> str:
    project_dir = create_cli_project()
    _write_manifest(project_dir)
    workspace = _workspace(Path(project_dir) / "baseline")
    monkeypatch.setattr("chipcompiler.data.load_workspace", lambda _path: workspace)
    monkeypatch.setattr("chipcompiler.data.refresh_workspace_config", lambda _workspace: None)
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", _Flow)
    return project_dir


def _param(project_dir: str, *args: str) -> int:
    return cli_main.run(["param", *args, "--workspace", "baseline", "--project", project_dir])


def test_workspace_param_diff_text_lists_a_local_override(capsys, create_cli_project, monkeypatch):
    project_dir = _project_with_workspace(create_cli_project, monkeypatch)
    assert _param(project_dir, "set", "placement:place.target_density", "0.65", "--plain") == 0
    capsys.readouterr()

    rc = _param(project_dir, "diff")

    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out.split() == [
        "placement:place.target_density",
        "0.65",
        "(was",
        "0.2,",
        "workspace)",
    ]
    assert "Traceback" not in captured.err


def test_workspace_param_diff_text_without_overrides(capsys, create_cli_project, monkeypatch):
    project_dir = _project_with_workspace(create_cli_project, monkeypatch)

    rc = _param(project_dir, "diff")

    assert rc == 0
    assert capsys.readouterr().out.strip() == "No overrides."


def test_param_diff_text_reads_the_default_of_a_project_override(capsys):
    render_param_diff_text(
        [{"param": "design.frequency_mhz", "value": 120.0, "default": 100.0, "source": "ecc.toml"}]
    )

    assert capsys.readouterr().out.split() == [
        "design.frequency_mhz",
        "120.0",
        "(was",
        "100.0,",
        "ecc.toml)",
    ]


def test_param_diff_text_keeps_a_default_of_none(capsys):
    """``default`` wins whenever the record has it, also when it is ``None``."""
    render_param_diff_text(
        [
            {
                "param": "cts.skew_bound",
                "value": 0.1,
                "default": None,
                "baseline": 5,
                "source": "ecc.toml",
            }
        ]
    )

    assert "(was None, ecc.toml)" in capsys.readouterr().out
