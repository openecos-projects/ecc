import json
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.engine.signoff_assessment import build_signoff_assessment
from chipcompiler.engine.signoff_export import SignoffExportError, _additional_file_path
from chipcompiler.engine.snapshot_limits import CHECKLIST_READ_MAX_BYTES


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


def test_advisory_failures_leave_signoff_available_for_attention_review(tmp_path):
    workspace = SimpleNamespace(
        directory=tmp_path,
        flow=SimpleNamespace(
            steps=lambda: [
                {"name": "Harden", "state": "Success"},
                {"name": "antennaCheck", "state": "Incomplete"},
                {"name": "emir", "state": "Incomplete"},
            ]
        ),
    )
    result = build_signoff_assessment(
        workspace,
        checklist={
            "schema_version": 3,
            "kind": "signoff_checklist",
            "status": "attention",
            "checklist": [
                {"step": name, "state": "warning", "blocked": False}
                for name in ("antennaCheck", "emir")
            ],
        },
    )
    assert result["status"] == "attention"
    assert all(risk["severity"] == "warning" for risk in result["risks"])


def test_malformed_checklist_is_reported_as_unavailable(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "checklist.json").write_text("[]")
    workspace = SimpleNamespace(directory=Path(tmp_path), flow=None)

    result = build_signoff_assessment(workspace)

    assert result["status"] == "blocked"


def test_oversized_checklist_is_reported_as_unavailable(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "checklist.json").write_text(
        '{"checklist":["' + "x" * CHECKLIST_READ_MAX_BYTES + '"]}',
        encoding="utf-8",
    )
    workspace = SimpleNamespace(directory=Path(tmp_path), flow=None)

    result = build_signoff_assessment(workspace)

    assert result["status"] == "blocked"
    assert result["risks"][0]["title"] == "Signoff checklist unavailable"


def test_signoff_additional_file_path_rejects_escape(tmp_path):
    package = tmp_path / "package"
    package.mkdir()

    for value in ("/tmp/escape", "../escape", "", ".", "bad\x00path"):
        try:
            _additional_file_path(package, value)
        except SignoffExportError:
            continue
        raise AssertionError(f"unsafe path accepted: {value!r}")
