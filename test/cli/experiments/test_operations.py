import json

import pytest

from chipcompiler.cli.experiments import operations


def _workspace(tmp_path, flow):
    workspace = tmp_path / "default"
    (workspace / "home").mkdir(parents=True)
    (workspace / "home" / "flow.json").write_text(json.dumps(flow), encoding="utf-8")
    return workspace


def test_collect_candidate_evidence_reads_a_blocked_flow_projection(tmp_path, monkeypatch):
    workspace = _workspace(
        tmp_path,
        {
            "steps": [
                {
                    "name": "sta",
                    "tool": "ecc",
                    "state": "Success",
                    "checklist_status": {"status": "blocked", "blocked": True},
                }
            ]
        },
    )
    monkeypatch.setattr(operations, "_json_command", lambda *_args: (0, []))

    evidence = operations.collect_candidate_evidence(tmp_path, workspace, 0)

    assert evidence["status"] == "blocked"
    assert evidence["step_statuses"] == [
        {"name": "sta", "status": "success", "checklist": "blocked"}
    ]


def test_collect_candidate_evidence_does_not_block_passed_flow_steps(tmp_path, monkeypatch):
    workspace = _workspace(
        tmp_path,
        {
            "steps": [
                {
                    "name": "sta",
                    "tool": "ecc",
                    "state": "Success",
                    "checklist_status": {"status": "passed", "blocked": False},
                }
            ]
        },
    )
    monkeypatch.setattr(operations, "_json_command", lambda *_args: (0, []))

    evidence = operations.collect_candidate_evidence(tmp_path, workspace, 0)

    assert evidence["status"] == "passed"
    assert evidence["step_statuses"] == [
        {"name": "sta", "status": "success", "checklist": "passed"}
    ]


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        (
            {"step": "sta", "status": "success", "checklist_status": "blocked"},
            "blocked",
        ),
        (
            {
                "step": "sta",
                "status": "success",
                "checklist_status": "unknown",
                "checklist_blocked": True,
            },
            "blocked",
        ),
        (
            {
                "step": "sta",
                "status": "success",
                "checklist_status": "passed",
                "checklist_blocked": False,
            },
            "passed",
        ),
    ],
)
def test_collect_candidate_evidence_reads_status_step_records(
    tmp_path, monkeypatch, record, expected
):
    workspace = _workspace(tmp_path, {"steps": []})
    payload = [
        {"workspace_id": "default", "status": "success", "workspace": str(workspace)},
        record,
    ]

    def json_command(_project, _workspace, command):
        return (0, payload if command == "status" else [])

    monkeypatch.setattr(operations, "_json_command", json_command)

    evidence = operations.collect_candidate_evidence(tmp_path, workspace, 0)

    assert evidence["status"] == expected
    assert evidence["step_statuses"][0]["checklist"] == expected


def test_collect_candidate_evidence_keeps_incomplete_steps_out_of_passed(tmp_path, monkeypatch):
    workspace = _workspace(
        tmp_path,
        {"steps": [{"name": "sta", "tool": "ecc", "state": "Incomplete"}]},
    )
    monkeypatch.setattr(operations, "_json_command", lambda *_args: (0, []))

    evidence = operations.collect_candidate_evidence(tmp_path, workspace, 0)

    assert evidence["step_statuses"] == [
        {"name": "sta", "status": "incomplete", "checklist": "unknown"}
    ]
