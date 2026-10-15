from types import SimpleNamespace

import pytest

from chipcompiler.cli.core.inputs import OutputOptions, ProjectOptions, RunInput
from chipcompiler.cli.core.types import CommandResult
from chipcompiler.cli.project.run_existing import run_existing_workspace


@pytest.mark.parametrize(
    "selectors",
    [
        {"from_step": "Synthesis", "to_step": "postFloorplan"},
        {"from_step": "place"},
        {"only": "place", "force": True},
        {"resume": True},
    ],
)
def test_manifest_workspace_honors_explicit_run_selectors(tmp_path, monkeypatch, selectors):
    command = RunInput(output=OutputOptions(), project=ProjectOptions(), **selectors)
    context = SimpleNamespace(project_dir=str(tmp_path), project_state="manifest")
    seen = []
    expected = CommandResult.ok([{"status": "success"}])

    def selected(request, path, identity, *, project_dir):
        seen.append((request, path, identity, project_dir))
        return expected

    monkeypatch.setattr("chipcompiler.cli.project.run_workspace.execute_workspace_run", selected)
    result = run_existing_workspace(
        command,
        context,
        SimpleNamespace(manifest_driven=True),
        str(tmp_path / "trial"),
        "trial",
        {},
        [],
        flow_config={"start_step": "Synthesis", "end_step": "Harden"},
        workspace_registered=True,
    )
    assert result == expected
    assert seen == [(command, str(tmp_path / "trial"), "trial", str(tmp_path))]
