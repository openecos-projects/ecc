import json

from chipcompiler.cli.project.revision import expected_revision_error


def _snapshot(workspace, revision: int) -> None:
    home = workspace / "home"
    home.mkdir(parents=True)
    (home / "engineering-snapshot.json").write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "workspaceId": "workspace-1",
                "workspaceRevision": revision,
                "flow": {},
                "parameters": {},
                "checklist": {},
                "analysis": {},
                "qorAssessment": {},
                "signoffAssessment": {},
                "artifacts": [],
            }
        ),
        encoding="utf-8",
    )


def test_expected_revision_match(tmp_path):
    workspace = tmp_path / "workspace"
    _snapshot(workspace, 7)

    assert expected_revision_error(workspace, 7, workspace_id="baseline") is None


def test_expected_revision_conflict_uses_reserved_exit_code(tmp_path):
    workspace = tmp_path / "workspace"
    _snapshot(workspace, 8)

    result = expected_revision_error(workspace, 7, workspace_id="baseline")

    assert result is not None
    assert result.exit_code == 21
    assert result.records[0]["error"] == "revision_conflict"
    assert result.records[0]["expected_revision"] == 7
    assert result.records[0]["actual_revision"] == 8
