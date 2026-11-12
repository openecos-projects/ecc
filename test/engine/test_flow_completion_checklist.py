import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from chipcompiler.engine.flow_completion import summarize_step_checklist


def _step(path: Path):
    return SimpleNamespace(name="drc", tool="ecc", checklist=SimpleNamespace(path=path))


def test_summarize_step_checklist_maps_ready_to_passed(tmp_path):
    path = tmp_path / "checklist.json"
    path.write_text(
        json.dumps(
            {
                "status": "ready",
                "summary": {"passed": 2, "blocked": 0},
                "requirements_status": "present",
                "checker_revision": "checklist-v3",
                "generated_at": "2026-10-12T00:00:00Z",
                "checklist": [{"id": "drc.clean", "blocked": False}],
            }
        )
    )

    result: Any = summarize_step_checklist(_step(path))

    assert result["status"] == "passed"
    assert result["blocked"] is False
    assert result["summary"]["passed"] == 2
    assert result["requirements_status"] == "present"
    assert result["revision"] == "checklist-v3"
    assert result["updated_at"] == "2026-10-12T00:00:00Z"
    assert "items" not in result


def test_summarize_step_checklist_preserves_blocked_items(tmp_path):
    path = tmp_path / "checklist.json"
    path.write_text(
        json.dumps(
            {
                "status": "blocked",
                "requirements_status": "present",
                "checklist": [{"id": "sta.setup", "blocked": True}],
            }
        )
    )

    result: Any = summarize_step_checklist(_step(path))

    assert result == {
        "status": "blocked",
        "blocked": True,
        "failed_items": ["sta.setup"],
        "requirements_status": "present",
        "source": str(path),
    }


def test_summarize_step_checklist_marks_no_requirements_explicitly(tmp_path):
    path = tmp_path / "checklist.json"
    path.write_text(
        json.dumps(
            {
                "status": "ready",
                "requirements_status": "none",
                "checklist": [],
            }
        )
    )

    result: Any = summarize_step_checklist(_step(path))

    assert result["status"] == "passed"
    assert result["requirements_status"] == "none"
    assert result["failed_items"] == []


def test_summarize_step_checklist_is_unknown_for_legacy_missing_file(tmp_path):
    result: Any = summarize_step_checklist(_step(tmp_path / "missing.json"))

    assert result["status"] == "unknown"
    assert result["blocked"] is False


def test_sync_step_checklist_persists_projection(tmp_path):
    from chipcompiler.engine.flow_completion import sync_step_checklist

    path = tmp_path / "checklist.json"
    path.write_text(
        json.dumps(
            {
                "status": "blocked",
                "requirements_status": "present",
                "checklist": [{"id": "drc", "blocked": True}],
            }
        )
    )
    step = _step(path)

    class Flow:
        def __init__(self):
            self.step = {"name": "drc", "tool": "ecc"}
            self.saved = False

        def get_step(self, name, tool):
            return self.step

        def save(self):
            self.saved = True
            return True

    flow = Flow()
    result: Any = sync_step_checklist(flow, step)

    assert result["status"] == "blocked"
    step_data: Any = flow.step
    assert "checklist" not in step_data
    assert step_data["checklist_status"]["blocked"] is True
    assert step_data["checklist_status"]["failed_items"] == ["drc"]
    assert flow.saved is True


def test_flow_items_ignore_steps_outside_the_ledger_range():
    from chipcompiler.tools.ecc.signoff_checklist import _flow_items

    steps = [
        {"name": "filler", "tool": "ecc", "state": "Success"},
        {"name": "Harden", "tool": "ecc", "state": "Success"},
    ]

    class Flow:
        def steps(self):
            return steps

        def has_step(self, name, tool=None):
            value = name.value if hasattr(name, "value") else name
            return any(step["name"] == value for step in steps)

    workspace = SimpleNamespace(
        flow=Flow(),
        directory=Path("/tmp/bounded-workspace"),
        design=SimpleNamespace(name="gcd"),
    )

    items = _flow_items(workspace)

    assert not any(item["step"] == "route" for item in items)
    assert any(item["step"] == "Harden" and item["state"] == "pass" for item in items)
