import json
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.cli import main as cli_main
from chipcompiler.data.parameter import Parameters
from chipcompiler.data.workspace import Flow


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
            path=parameters_path.parent / "flow.json",
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


def test_workspace_sta_parallel_limit_replays_into_config(create_cli_project, monkeypatch):
    from chipcompiler.data.workspace.config_overrides import apply_config_overrides

    project_dir = create_cli_project()
    workspace_dir = Path(project_dir) / "baseline"
    _write_manifest(project_dir)
    workspace = _workspace(workspace_dir)
    workspace.flow.data["steps"].append(
        {"name": "sta", "state": "Success", "runtime": "", "peak memory (mb)": 0}
    )
    config_path = workspace_dir / "sta.json"
    config_path.write_text('{"max_parallel_corners": 1, "signoff": []}')
    workspace.config["sta"] = config_path
    monkeypatch.setattr("chipcompiler.data.load_workspace", lambda _: workspace)
    monkeypatch.setattr(
        "chipcompiler.data.refresh_workspace_config",
        lambda current: apply_config_overrides(current.config, current.parameters.data),
    )
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", _Flow)
    assert (
        cli_main.run(
            [
                "param",
                "set",
                "sta.max_parallel_corners",
                "13",
                "--workspace",
                "baseline",
                "--project",
                project_dir,
                "--plain",
            ]
        )
        == 0
    )
    assert json.loads(config_path.read_text()) == {"max_parallel_corners": 13, "signoff": []}
    assert workspace.flow.data["steps"][-1]["state"] == "Unstart"
    assert workspace.parameters.data["config_overrides"] == {"sta": {"max_parallel_corners": 13}}
    before = workspace.parameters.path.read_bytes()
    for value in ("0", "-1", "2.5", "true"):
        assert (
            cli_main.run(
                [
                    "param",
                    "set",
                    "sta.max_parallel_corners",
                    value,
                    "--workspace",
                    "baseline",
                    "--project",
                    project_dir,
                    "--plain",
                ]
            )
            == 1
        )
        assert workspace.parameters.path.read_bytes() == before
        assert json.loads(config_path.read_text())["max_parallel_corners"] == 13


def test_workspace_param_set_persists_and_invalidates_suffix(
    capsys, create_cli_project, monkeypatch, plain_records
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
            "--plain",
        ]
    )

    assert rc == 0
    record = plain_records(capsys.readouterr().out)[0]
    assert record["value"] == "0.65"
    assert record["from_step"] == "place"
    assert record["invalidated_steps"] == "['place', 'route']"
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
            "--plain",
        ]
    )

    assert rc == 0
    assert plain_records(capsys.readouterr().out)[0]["value"] == "0.2"
    assert workspace.parameters.data["dreamplace"]["target_density"] == 0.2


def test_workspace_param_refresh_failure_rolls_back_params(
    capsys, create_cli_project, monkeypatch, plain_records
):
    project_dir = create_cli_project()
    workspace_dir = Path(project_dir) / "baseline"
    _write_manifest(project_dir)
    workspace = _workspace(workspace_dir)
    derived_manifest = workspace_dir / "home" / "config-derived-manifest.json"
    derived_manifest.write_text('{"files":{"cts_ecc.json":{"sha256":"before"}}}')
    manifest_before = derived_manifest.read_bytes()
    monkeypatch.setattr("chipcompiler.data.load_workspace", lambda _path: workspace)

    def fail_refresh(_workspace):
        raise RuntimeError("config regeneration exploded")

    monkeypatch.setattr("chipcompiler.data.refresh_workspace_config", fail_refresh)
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
            "--plain",
        ]
    )

    assert rc == 1
    record = plain_records(capsys.readouterr().out)[0]
    assert record["error"] == "workspace_param_refresh_failed"
    # The parameter mutation was already persisted when the refresh failed;
    # the rollback must put params.toml back, not leave new parameters
    # paired with old configs and an untouched ledger. params.toml did not
    # exist before the mutation, so restoring it means removing it again.
    assert not workspace.parameters.path.exists()
    assert derived_manifest.read_bytes() == manifest_before
    assert [step["state"] for step in workspace.flow.data["steps"]] == [
        "Success",
        "Success",
        "Success",
    ]


def test_workspace_param_list_honors_step_filter(
    capsys, create_cli_project, monkeypatch, plain_records
):
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
            "place",
            "--project",
            project_dir,
            "--plain",
        ]
    )

    assert rc == 0
    record = plain_records(capsys.readouterr().out)[0]
    assert record["id"] == "place.target_density"
    assert record["value_literal"] == "0.2"


def test_workspace_param_list_rejects_unknown_step(
    capsys, create_cli_project, monkeypatch, plain_records
):
    project_dir = create_cli_project()
    workspace_dir = Path(project_dir) / "baseline"
    _write_manifest(project_dir)
    workspace = _workspace(workspace_dir)
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
            "--plain",
        ]
    )

    assert rc == 1
    assert plain_records(capsys.readouterr().err)[0] == {
        "kind": "error",
        "error": "unknown_step",
        "step": "cts",
    }


def test_workspace_param_list_matches_first_step_configuration(
    capsys, create_cli_project, monkeypatch, plain_records
):
    project_dir = create_cli_project()
    workspace_dir = Path(project_dir) / "baseline"
    _write_manifest(project_dir)
    workspace = _workspace(workspace_dir)
    monkeypatch.setattr("chipcompiler.data.load_workspace", lambda _path: workspace)

    rc = cli_main.run(
        [
            "param",
            "list",
            "--workspace",
            "baseline",
            "--step",
            "synthesis",
            "--all",
            "--project",
            project_dir,
            "--plain",
        ]
    )

    assert rc == 0
    records = plain_records(capsys.readouterr().out)
    assert [record["id"] for record in records] == [
        "design.frequency_mhz",
        "flow.run_analysis",
        "geometry.clock_tree",
    ]
    assert records[0]["record"] == "parameter"
    assert records[0]["step_id"] == "Synthesis"
    assert records[0]["type"] == "float"
    assert records[0]["applies_to"] == "synthesis"
    assert records[0]["value_literal"] == "100.0"


def test_workspace_param_list_hydrates_persisted_flow_ledger(
    capsys, create_cli_project, monkeypatch, plain_records
):
    project_dir = create_cli_project()
    workspace_dir = Path(project_dir) / "baseline"
    _write_manifest(project_dir)
    workspace = _workspace(workspace_dir)
    flow_data = workspace.flow.data
    workspace.flow = Flow(path=workspace_dir / "home" / "flow.json")
    assert workspace.flow.path is not None
    workspace.flow.path.parent.mkdir(parents=True, exist_ok=True)
    workspace.flow.path.write_text(json.dumps(flow_data), encoding="utf-8")
    monkeypatch.setattr("chipcompiler.data.load_workspace", lambda _path: workspace)

    rc = cli_main.run(
        [
            "param",
            "list",
            "--workspace",
            "baseline",
            "--step",
            "synthesis",
            "--all",
            "--project",
            project_dir,
            "--plain",
        ]
    )

    assert rc == 0
    records = plain_records(capsys.readouterr().out)
    assert [record["id"] for record in records] == [
        "design.frequency_mhz",
        "flow.run_analysis",
        "geometry.clock_tree",
    ]
    assert records[0]["step_id"] == "Synthesis"
