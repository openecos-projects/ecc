import json
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.engine.signoff_assessment import build_signoff_assessment
from chipcompiler.engine.signoff_export import SignoffExportError, _additional_file_path


def test_stale_checklist_cannot_make_incomplete_flow_ready(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "checklist.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "kind": "signoff_checklist",
                "status": "ready",
                "checklist": [],
            }
        )
    )
    workspace = SimpleNamespace(
        directory=Path(tmp_path),
        flow=SimpleNamespace(steps=lambda: [{"name": "Synthesis", "state": "Unstart"}]),
    )

    result = build_signoff_assessment(workspace)

    assert result["status"] == "blocked"


def test_malformed_checklist_is_reported_as_unavailable(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "checklist.json").write_text("[]")
    workspace = SimpleNamespace(directory=Path(tmp_path), flow=None)

    result = build_signoff_assessment(workspace)

    assert result["status"] == "blocked"


def test_signoff_additional_file_path_rejects_escape(tmp_path):
    package = tmp_path / "package"
    package.mkdir()

    for value in ("/tmp/escape", "../escape", "", ".", "bad\x00path"):
        try:
            _additional_file_path(package, value)
        except SignoffExportError:
            continue
        raise AssertionError(f"unsafe path accepted: {value!r}")
