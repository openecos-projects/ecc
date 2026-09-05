import json
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.cli import main as cli_main
from chipcompiler.data.parameter import Parameters


class _Flow:
    def __init__(self, workspace):
        self.workspace = workspace

    def save(self):
        return True


def _workspace(workspace_dir):
    parameters_path = workspace_dir / "home" / "params.toml"
    parameters_path.parent.mkdir(parents=True)
    return SimpleNamespace(
        directory=workspace_dir,
        parameters=Parameters(
            path=parameters_path,
            data={
                "pdk": "ics55",
                "design": "gcd",
                "top_module": "gcd",
                "clock": "clk",
                "dreamplace": {"target_density": 0.2},
            },
        ),
        config={},
        flow=SimpleNamespace(
            data={
                "steps": [
                    {"name": "Synthesis", "state": "Success", "runtime": "", "peak memory (mb)": 0},
                    {"name": "place", "state": "Success", "runtime": "", "peak memory (mb)": 0},
                    {"name": "route", "state": "Success", "runtime": "", "peak memory (mb)": 0},
                ]
            }
        ),
    )


def _write_manifest(project_dir: str) -> None:
    project_path = Path(project_dir)
    (project_path / "project.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "design_name": "gcd",
                "root_path": project_dir,
                "base_design": {
                    "pdk": "ics55",
                    "pdk_root": str(project_path / "ics55"),
                    "top_module": "gcd",
                    "clock": "clk",
                    "rtl_list": ["rtl/gcd.v"],
                    "parameters": {"design": "gcd", "frequency_max": 100},
                },
                "workspaces": [
                    {
                        "workspace_id": "baseline",
                        "workspace_path": str(project_path / "baseline"),
                        "status": "success",
                    }
                ],
            }
        )
    )


def test_workspace_param_set_persists_and_invalidates_suffix(
    capsys, create_cli_project, monkeypatch
):
    project_dir = create_cli_project()
    workspace_dir = Path(project_dir) / "baseline"
    _write_manifest(project_dir)
    workspace = _workspace(workspace_dir)
    monkeypatch.setattr("chipcompiler.data.load_workspace", lambda _path: workspace)
    monkeypatch.setattr("chipcompiler.data.refresh_workspace_config", lambda _workspace: None)
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", _Flow)

    rc = cli_main.run(
        [
            "param",
            "set",
            "place.target_density",
            "0.65",
            "--workspace",
            "baseline",
            "--project",
            project_dir,
            "--json",
        ]
    )

    assert rc == 0
    record = json.loads(capsys.readouterr().out)["records"][0]
    assert record["value"] == 0.65
    assert record["from_step"] == "place"
    assert record["invalidated_steps"] == ["place", "route"]
    assert workspace.parameters.data["dreamplace"]["target_density"] == 0.65
    assert [step["state"] for step in workspace.flow.data["steps"]] == [
        "Success",
        "Unstart",
        "Unstart",
    ]
    assert "workspace_param_overrides" in workspace.parameters.path.read_text()

    rc = cli_main.run(
        [
            "param",
            "unset",
            "place.target_density",
            "--workspace",
            "baseline",
            "--project",
            project_dir,
            "--json",
        ]
    )

    assert rc == 0
    assert json.loads(capsys.readouterr().out)["records"][0]["value"] == 0.2
    assert workspace.parameters.data["dreamplace"]["target_density"] == 0.2


def test_workspace_param_list_honors_step_filter(capsys, create_cli_project, monkeypatch):
    project_dir = create_cli_project()
    workspace_dir = Path(project_dir) / "baseline"
    _write_manifest(project_dir)
    workspace = _workspace(workspace_dir)
    workspace.parameters.data["workspace_param_overrides"] = [
        {"key": "place.target_density", "baseline": 0.2, "value": 0.65}
    ]
    monkeypatch.setattr("chipcompiler.data.load_workspace", lambda _path: workspace)

    rc = cli_main.run(
        [
            "param",
            "list",
            "--workspace",
            "baseline",
            "--step",
            "cts",
            "--project",
            project_dir,
            "--json",
        ]
    )

    assert rc == 0
    assert json.loads(capsys.readouterr().out)["records"] == [
        {"param": "list", "status": "clean", "workspace": "baseline"}
    ]
