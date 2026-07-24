import json
from pathlib import Path

from chipcompiler.data.checklist import (
    CHECKLIST_REVISION,
    CHECKLIST_SCHEMA_VERSION,
    Checklist,
)


def test_checklist_creates_current_signoff_contract(tmp_path):
    path = tmp_path / "checklist.json"

    checklist = Checklist(path)

    assert isinstance(checklist.path, Path)
    assert checklist.path == path
    data = json.loads(path.read_text())
    assert data["schema_version"] == CHECKLIST_SCHEMA_VERSION == 3
    assert data["kind"] == "signoff_checklist"
    assert data["checker_revision"] == CHECKLIST_REVISION
    assert data["status"] == "ready"
    assert data["summary"] == {
        "passed": 0,
        "blocked": 0,
        "attention": 0,
        "unavailable": 0,
    }
    assert data["checklist"] == []
    assert data["generated_at"].endswith("Z")


def test_checklist_replaces_legacy_data_with_current_snapshot(tmp_path):
    path = tmp_path / "checklist.json"
    path.write_text(
        json.dumps({"checklist": [{"step": "drc", "item": "obsolete check"}]}),
        encoding="utf-8",
    )

    checklist = Checklist(path)
    assert checklist.data["checklist"] == []

    checklist.replace([
        {
            "id": "quality.drc.clean",
            "step": "drc",
            "category": "quality_gate",
            "owner": "qor",
            "policy": "block",
            "state": "failed",
            "title": "Final DRC clean",
            "summary": "drc_count=2 (required == 0)",
            "source": {"kind": "qor_gate", "path": "drc_ecc/analysis/qor_summary.json"},
            "evidence": [{"kind": "feature", "path": "drc_ecc/feature/drc.step.json"}],
        },
        {
            "id": "report.optional.image",
            "step": "workspace",
            "category": "report",
            "owner": "checklist",
            "policy": "warn",
            "state": "warning",
            "title": "Optional image",
        },
    ])

    assert checklist.data["status"] == "blocked"
    assert checklist.data["summary"] == {
        "passed": 0,
        "blocked": 1,
        "attention": 1,
        "unavailable": 0,
    }
    drc = checklist.data["checklist"][0]
    assert drc["blocked"] is True
    assert drc["owner"] == "qor"
    assert drc["source"]["kind"] == "qor_gate"
