from chipcompiler.cli.project.revision import expected_revision_error


def _snapshot(workspace, revision: int) -> None:
    from types import SimpleNamespace

    from chipcompiler.engine.snapshot import create_engineering_snapshot

    create_engineering_snapshot(
        SimpleNamespace(
            directory=workspace,
            flow=SimpleNamespace(data={"steps": []}),
            parameters=SimpleNamespace(data={"design": "gcd"}),
            design=SimpleNamespace(name="gcd"),
        ),
        workspace_id="workspace-1",
        workspace_revision=revision,
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
