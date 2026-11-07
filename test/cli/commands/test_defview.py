from pathlib import Path
from unittest.mock import Mock

from chipcompiler.cli.command_handlers import defview as defview_handler
from chipcompiler.cli.core.inputs import DefviewInput, OutputOptions, ProjectOptions
from chipcompiler.cli.core.types import CommandContext, OutputMode
from chipcompiler.data import OriginDesign, Workspace


def _context(workspace: Path) -> CommandContext:
    return CommandContext(
        project_dir=str(workspace.parent),
        project=str(workspace.parent),
        run_dir=str(workspace),
        run_id=workspace.name,
        output_mode=OutputMode.TEXT,
    )


def _input(def_path: Path) -> DefviewInput:
    return DefviewInput(
        output=OutputOptions(),
        project=ProjectOptions(),
        workspace=None,
        def_path=str(def_path),
    )


def test_defview_reuses_loaded_workspace_and_publishes_geometry(tmp_path, monkeypatch):
    workspace = Workspace(
        directory=tmp_path / "workspace",
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    flow_path = workspace.directory / "home" / "flow.json"
    flow_path.parent.mkdir(parents=True)
    flow_path.write_text('{"steps": []}\n', encoding="utf-8")
    source_def = tmp_path / "selected.def"
    source_def.write_text("VERSION 5.8 ;\n", encoding="utf-8")
    captured = {}

    def fake_run_defview(*, workspace, step):
        captured["workspace"] = workspace
        captured["step"] = step
        assert step.output.geometry is not None
        step.output.geometry.mkdir(parents=True)
        step.output.geometry_manifest.write_text("schema_version=1\n", encoding="utf-8")
        return True

    monkeypatch.setattr(
        defview_handler,
        "resolve_loaded_workspace",
        lambda _input, _ctx: (workspace, None),
    )
    monkeypatch.setattr(defview_handler, "run_defview", fake_run_defview)

    result = defview_handler.defview(_input(source_def), _context(workspace.directory))

    step = captured["step"]
    assert result.exit_code == 0
    assert captured["workspace"] is workspace
    assert step.directory == workspace.directory / "defview"
    assert step.input.def_ == source_def.resolve()
    assert step.output.def_ == workspace.directory / "defview" / "output" / "defview.def"
    assert step.output.geometry == (workspace.directory / "defview" / "output" / "geometry")
    assert result.records[0]["geometry_manifest"] == str(step.output.geometry_manifest)
    assert flow_path.read_text(encoding="utf-8") == '{"steps": []}\n'


def test_defview_rejects_missing_def_without_running(tmp_path, monkeypatch):
    workspace = Workspace(directory=tmp_path / "workspace")
    run_defview = Mock()
    monkeypatch.setattr(
        defview_handler,
        "resolve_loaded_workspace",
        lambda _input, _ctx: (workspace, None),
    )
    monkeypatch.setattr(defview_handler, "run_defview", run_defview)

    result = defview_handler.defview(
        _input(tmp_path / "missing.def"), _context(workspace.directory)
    )

    assert result.exit_code != 0
    assert result.records[0]["error"] == "defview_failed"
    assert "does not exist" in result.records[0]["reason"]
    run_defview.assert_not_called()


def test_defview_reports_geometry_generation_failure(tmp_path, monkeypatch):
    workspace = Workspace(
        directory=tmp_path / "workspace",
        design=OriginDesign(name="gcd"),
    )
    source_def = tmp_path / "selected.def"
    source_def.write_text("VERSION 5.8 ;\n", encoding="utf-8")
    monkeypatch.setattr(
        defview_handler,
        "resolve_loaded_workspace",
        lambda _input, _ctx: (workspace, None),
    )
    monkeypatch.setattr(defview_handler, "run_defview", lambda **_kwargs: False)

    result = defview_handler.defview(_input(source_def), _context(workspace.directory))

    assert result.exit_code != 0
    assert result.records[0]["error"] == "defview_failed"
    assert result.records[0]["def_path"] == str(source_def.resolve())


def test_defview_reports_design_read_failure(tmp_path, monkeypatch):
    workspace = Workspace(
        directory=tmp_path / "workspace",
        design=OriginDesign(name="gcd"),
    )
    source_def = tmp_path / "selected.def"
    source_def.write_text("not a valid DEF\n", encoding="utf-8")
    monkeypatch.setattr(
        defview_handler,
        "resolve_loaded_workspace",
        lambda _input, _ctx: (workspace, None),
    )

    def fail_to_read(**_kwargs):
        raise RuntimeError("ECC failed to read DEF input")

    monkeypatch.setattr(defview_handler, "run_defview", fail_to_read)

    result = defview_handler.defview(_input(source_def), _context(workspace.directory))

    assert result.exit_code != 0
    assert result.records[0]["error"] == "defview_failed"
    assert "ECC failed to read DEF input" in result.records[0]["reason"]
