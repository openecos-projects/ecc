import json
from pathlib import Path

from chipcompiler.cli.command_handlers import gds_view
from chipcompiler.cli.core.inputs import GdsViewInput, OutputOptions, ProjectOptions
from chipcompiler.cli.core.types import CommandContext, OutputMode
from chipcompiler.tools.klayout_tool.viewer import KlayoutUnavailableError


def _context(workspace: Path) -> CommandContext:
    return CommandContext(
        project_dir=str(workspace.parent),
        project=str(workspace.parent),
        run_dir=str(workspace),
        run_id=workspace.name,
        output_mode=OutputMode.TEXT,
    )


def _workspace(tmp_path: Path, *, gds: bool = True, multiple: bool = False) -> Path:
    workspace = tmp_path / "workspace"
    output = workspace / "Harden_ecc" / "output"
    output.mkdir(parents=True)
    if gds:
        (output / "gcd_Harden.gds").write_bytes(b"GDS")
        if multiple:
            (output / "gcd_Harden_extra.gds").write_bytes(b"GDS")
    (workspace / "home").mkdir(parents=True)
    (workspace / "home" / "flow.json").write_text(
        json.dumps({"steps": [{"name": "Harden", "tool": "ecc", "state": "Success"}]}),
        encoding="utf-8",
    )
    return workspace


def _input(step: str = "Harden") -> GdsViewInput:
    return GdsViewInput(output=OutputOptions(), project=ProjectOptions(), step=step)


def test_gds_view_rejects_step_without_gds(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path, gds=False)
    result = gds_view.gds_view(_input(), _context(workspace))

    assert result.exit_code != 0
    assert result.records[0]["error"] == "gds_view_unavailable"
    assert "does not publish a GDS" in result.records[0]["reason"]


def test_gds_view_rejects_multiple_gds_outputs(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path, multiple=True)
    result = gds_view.gds_view(_input(), _context(workspace))

    assert result.exit_code != 0
    assert result.records[0]["error"] == "gds_view_ambiguous"


def test_gds_view_checks_display_before_opening(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    for key in ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET"):
        monkeypatch.delenv(key, raising=False)

    result = gds_view.gds_view(_input(), _context(workspace))

    assert result.exit_code != 0
    assert result.records[0]["error"] == "gds_view_display_unavailable"


def test_gds_view_opens_the_selected_step_gds(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    monkeypatch.setenv("DISPLAY", ":99")
    opened = []
    monkeypatch.setattr(gds_view, "view_gds", lambda path: opened.append(path))

    result = gds_view.gds_view(_input(), _context(workspace))

    assert result.exit_code == 0
    assert opened == [workspace / "Harden_ecc/output/gcd_Harden.gds"]
    assert result.records[0]["status"] == "closed"


def test_gds_view_reports_missing_klayout_gui(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(
        gds_view,
        "view_gds",
        lambda path: (_ for _ in ()).throw(
            KlayoutUnavailableError("KLayout GUI executable was not found")
        ),
    )

    result = gds_view.gds_view(_input(), _context(workspace))

    assert result.exit_code != 0
    assert result.records[0]["error"] == "gds_view_klayout_unavailable"
