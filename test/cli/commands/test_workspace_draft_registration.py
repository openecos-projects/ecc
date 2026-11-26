import json

import pytest

from chipcompiler.cli import main as cli_main


def test_registered_draft_with_missing_directory_is_rejected_before_build(
    fresh_project, capsys, monkeypatch
):
    args = [
        "workspace",
        "create",
        "draft",
        "--project",
        str(fresh_project),
        "--draft",
        "{}",
        "--json",
    ]
    assert cli_main.run(args) == 0
    workspace = fresh_project / "draft"
    workspace.rename(fresh_project.parent / "moved")
    manifest = fresh_project / "project.json"
    original = manifest.read_bytes()
    monkeypatch.setattr(
        "chipcompiler.cli.project.run_prepare.build_fresh_workspace",
        lambda *args, **kwargs: pytest.fail("registered draft reached the builder"),
    )

    for extra in (["--preview"], []):
        capsys.readouterr()
        assert cli_main.run([*args, *extra]) == 1
        assert json.loads(capsys.readouterr().out) == [
            {
                "kind": "error",
                "error": "run_exists",
                "workspace_id": "draft",
                "workspace": str(workspace),
                "reason": "Workspace already registered: draft",
            }
        ]
        assert manifest.read_bytes() == original
        assert not workspace.exists()
