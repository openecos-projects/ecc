import json
from pathlib import Path

from chipcompiler.cli.command_handlers import chipview
from chipcompiler.cli.core.inputs import ChipviewInput, OutputOptions, ProjectOptions
from chipcompiler.cli.core.types import CommandContext, OutputMode


def _context(workspace: Path) -> CommandContext:
    return CommandContext(
        project_dir=str(workspace.parent),
        project=str(workspace.parent),
        run_dir=str(workspace),
        run_id=workspace.name,
        output_mode=OutputMode.TEXT,
    )


def _manifest(geometry: Path) -> None:
    geometry.mkdir(parents=True, exist_ok=True)
    files = {
        "meta": "geometry.meta.bin",
        "shapes": "geometry.shapes.bin",
        "owners": "geometry.owners.bin",
        "payload": "geometry.payload.bin",
        "names": "geometry.names.bin",
        "name_index": "geometry.name_index.bin",
        "sidmap": "geometry.sidmap.bin",
        "view": "geometry.view.bin",
    }
    for name in files.values():
        (geometry / name).write_bytes(b"x")
    lines = ["schema_version=1", "shape_count=1", "owner_count=1", "payload_size=1"]
    lines.extend(f"{key}={value}" for key, value in files.items())
    (geometry / "geometry.manifest").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _workspace(tmp_path: Path, *, step: str = "route") -> Path:
    workspace = tmp_path / "workspace"
    step_dir = workspace / "route_ecc" / "output"
    _manifest(step_dir / "geometry")
    (workspace / "home").mkdir(parents=True)
    (workspace / "home" / "flow.json").write_text(
        json.dumps({"steps": [{"name": step, "tool": "ecc", "state": "Success"}]}),
        encoding="utf-8",
    )
    return workspace


def _input(step: str = "route") -> ChipviewInput:
    return ChipviewInput(
        output=OutputOptions(),
        project=ProjectOptions(),
        step=step,
    )


def test_chipview_rejects_missing_display(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    viewer = tmp_path / "chip-viewer-native"
    viewer.write_text("#!/bin/sh\n", encoding="utf-8")
    viewer.chmod(0o755)
    monkeypatch.setenv("ECOS_CHIP_VIEWER_BIN", str(viewer))
    for key in ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET"):
        monkeypatch.delenv(key, raising=False)

    result = chipview.chipview(_input(), _context(workspace))

    assert result.exit_code != 0
    assert result.records[0]["error"] == "chipview_display_unavailable"


def test_chipview_reports_missing_viewer(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("ECOS_CHIP_VIEWER_BIN", raising=False)
    monkeypatch.delenv("ECOS_ELECTRON_RESOURCES_PATH", raising=False)

    result = chipview.chipview(_input(), _context(workspace))

    assert result.exit_code != 0
    assert result.records[0]["error"] == "chipview_viewer_unavailable"
    assert "built-in terminal" in result.records[0]["reason"]


def test_chipview_reports_unknown_step(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    monkeypatch.setenv("DISPLAY", ":99")

    result = chipview.chipview(_input("cts"), _context(workspace))

    assert result.exit_code != 0
    assert result.records[0]["error"] == "chipview_step_not_found"
    assert "route" in result.records[0]["available"]


def test_chipview_rejects_incomplete_geometry_manifest(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    manifest = workspace / "route_ecc/output/geometry/geometry.manifest"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("geometry.view.bin", "missing.view.bin"),
        encoding="utf-8",
    )
    monkeypatch.setenv("DISPLAY", ":99")

    result = chipview.chipview(_input("route"), _context(workspace))

    assert result.exit_code != 0
    assert result.records[0]["error"] == "chipview_geometry_invalid"
    assert "view" in result.records[0]["reason"]


def test_chipview_launches_viewer_with_geometry_manifest(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    viewer = tmp_path / "chip-viewer-native"
    viewer.write_text("#!/bin/sh\n", encoding="utf-8")
    viewer.chmod(0o755)
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setenv("ECOS_CHIP_VIEWER_BIN", str(viewer))
    monkeypatch.setattr(chipview, "_STARTUP_CHECK_SECONDS", 0.0)

    class FakeProcess:
        pid = 1234

        def poll(self):
            return None

    calls = []

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(chipview.subprocess, "Popen", fake_popen)
    result = chipview.chipview(_input("route_ecc"), _context(workspace))

    assert result.exit_code == 0
    record = result.records[0]
    assert record["status"] == "started"
    assert record["viewer_source"] == "ECOS_CHIP_VIEWER_BIN"
    manifest = workspace / "route_ecc/output/geometry/geometry.manifest"
    assert calls[0][0][:3] == [str(viewer), "--manifest", str(manifest)]
    assert calls[0][0][-2:] == ["--mode", "view"]
