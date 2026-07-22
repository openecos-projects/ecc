import json
from pathlib import Path

from chipcompiler.data.checklist import (
    CHECKLIST_REVISION,
    CHECKLIST_SCHEMA_VERSION,
    Checklist,
    CheckState,
)


def test_checklist_accepts_path_and_persists_string_path(tmp_path):
    path = tmp_path / "checklist.json"

    checklist = Checklist(path)

    assert isinstance(checklist.path, Path)
    assert checklist.path == path
    data = json.loads(path.read_text())
    assert data["schema_version"] == CHECKLIST_SCHEMA_VERSION
    assert data["checker_revision"] == CHECKLIST_REVISION
    assert data["path"] == str(path)
    assert data["checklist"] == []
    assert data["generated_at"].endswith("Z")


def test_checklist_replaces_legacy_data_and_step_snapshot(tmp_path):
    path = tmp_path / "checklist.json"
    path.write_text(
        json.dumps(
            {
                "path": str(path),
                "checklist": [
                    {
                        "step": "drc",
                        "type": "DRC",
                        "item": "obsolete check",
                        "state": "Failed",
                        "info": "legacy",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    checklist = Checklist(path)
    assert checklist.data["checklist"] == []

    checklist.add("drc", "DRC", "check violation count", CheckState.Passed)
    checklist.add("sta", "Timing", "check setup", CheckState.Warning, "No timing exception data")
    checklist.replace_step(
        "drc",
        [
            {
                "type": "DRC",
                "item": "check violation count",
                "state": CheckState.Passed,
            },
            {
                "type": "Signoff",
                "item": "check final DRC requirement",
                "state": CheckState.Passed,
            },
        ],
    )

    assert checklist.data["checklist"] == [
        {
            "step": "sta",
            "type": "Timing",
            "item": "check setup",
            "state": "Warning",
            "info": "No timing exception data",
        },
        {
            "step": "drc",
            "type": "DRC",
            "item": "check violation count",
            "state": "Passed",
            "info": "",
        },
        {
            "step": "drc",
            "type": "Signoff",
            "item": "check final DRC requirement",
            "state": "Passed",
            "info": "",
        },
    ]
