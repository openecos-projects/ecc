import json
from pathlib import Path

from chipcompiler.cli.experiments.operations import diagnose_workspace


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_diagnose_workspace_uses_current_flow_and_qor_schema(tmp_path):
    project = tmp_path / "project"
    workspace = project / "ws_0001"
    _write_json(
        workspace / "home" / "flow.json",
        {
            "steps": [
                {"name": "Synthesis", "tool": "yosys", "state": "Success"},
                {"name": "Harden", "tool": "ecc", "state": "Unstart"},
            ]
        },
    )
    _write_json(
        workspace / "home" / "checklist.json",
        {
            "status": "blocked",
            "checklist": [
                {
                    "id": "quality.sta.hold_closed",
                    "state": "failed",
                    "blocked": True,
                    "policy": "block",
                }
            ],
        },
    )
    _write_json(
        workspace / "home" / "qor_report.json",
        {"scalar_summary": {"score": 0.0, "status": "FAIL"}},
    )

    assert diagnose_workspace(project, "ws_0001") == {
        "status": "blocked",
        "project": str(project),
        "workspace": str(workspace),
        "flow": {"status": "partial", "failed_steps": []},
        "checklist": {
            "status": "blocked",
            "blocked_count": 1,
            "blocked_items": ["quality.sta.hold_closed"],
        },
        "qor": {"available": True, "score": 0.0},
        "missing_artifacts": [],
        "next_actions": [
            f"ecc report checklist --project {project} --workspace ws_0001",
            f"ecc run --project {project} --workspace ws_0001 --resume",
        ],
    }


def test_diagnose_workspace_reports_non_advisory_failed_step(tmp_path):
    project = tmp_path / "project"
    workspace = project / "ws_0001"
    _write_json(
        workspace / "home" / "flow.json",
        {
            "steps": [
                {"name": "Synthesis", "tool": "yosys", "state": "Incomplete"},
                {"name": "Harden", "tool": "ecc", "state": "Unstart"},
            ]
        },
    )
    _write_json(workspace / "home" / "checklist.json", {"status": "ready", "checklist": []})
    _write_json(
        workspace / "home" / "qor_report.json",
        {"scalar_summary": {"score": 12.5, "status": "RED"}},
    )

    result = diagnose_workspace(project, "ws_0001")

    assert result["status"] == "failed"
    assert result["flow"] == {"status": "failed", "failed_steps": ["Synthesis"]}
    assert result["qor"] == {"available": True, "score": 12.5}


def test_diagnose_workspace_does_not_fail_on_advisory_step(tmp_path):
    project = tmp_path / "project"
    workspace = project / "ws_0001"
    _write_json(
        workspace / "home" / "flow.json",
        {
            "steps": [
                {"name": "antennaCheck", "tool": "ecc", "state": "Incomplete"},
                {"name": "emir", "tool": "ecc", "state": "Success"},
                {"name": "Harden", "tool": "ecc", "state": "Unstart"},
            ]
        },
    )
    _write_json(workspace / "home" / "checklist.json", {"status": "ready", "checklist": []})
    _write_json(
        workspace / "home" / "qor_report.json",
        {"scalar_summary": {"score": 50.0, "status": "RED"}},
    )

    result = diagnose_workspace(project, "ws_0001")

    assert result["status"] == "attention"
    assert result["flow"] == {"status": "partial", "failed_steps": []}
