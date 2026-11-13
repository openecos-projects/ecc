import importlib.util
from pathlib import Path

from chipcompiler.cli.experiments.operations import select_experiment_workspace
from chipcompiler.project.manifest import load_manifest


def _load_smoke_module():
    path = Path(__file__).parents[2] / "packaging" / "reproducible_cli_smoke.py"
    spec = importlib.util.spec_from_file_location("ecc_reproducible_cli_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_project_manifest_selects_the_smoke_workspace(tmp_path):
    project = tmp_path / "project"
    workspace = project / "smoke"
    (workspace / "home").mkdir(parents=True)

    _load_smoke_module().write_project_manifest(project, "smoke")

    manifest = load_manifest(str(project))
    assert manifest.design_name == "smoke"
    assert [entry.workspace_id for entry in manifest.active_workspaces()] == ["smoke"]
    name, directory, error = select_experiment_workspace(project, "smoke")
    assert (name, directory, error) == ("smoke", workspace.resolve(), None)
