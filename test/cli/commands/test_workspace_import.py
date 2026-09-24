import json
from pathlib import Path

from chipcompiler.cli import main as cli_main
from chipcompiler.data.parameter import Parameters, save_parameter


def _existing_workspace(
    path: Path,
    *,
    design: str = "gcd",
    pdk: str = "ics55",
    state: str = "Success",
) -> None:
    home = path / "home"
    home.mkdir(parents=True)
    (home / "flow.json").write_text(
        json.dumps(
            {
                "steps": [
                    {
                        "name": "Synthesis",
                        "tool": "yosys",
                        "state": state,
                    }
                ]
            }
        )
    )
    assert save_parameter(
        Parameters(
            path=home / "params.toml",
            data={
                "pdk": pdk,
                "design": design,
                "top_module": design,
                "clock": "clk",
                "frequency_max": 125,
                "max_fanout": 16,
                "_flow": {"start": "Synthesis", "end": "Synthesis"},
            },
        )
    )


def test_import_external_workspace_registers_metadata_without_changing_workspace(
    tmp_path, capsys, create_cli_project, plain_records
):
    project_dir = create_cli_project()
    workspace = tmp_path / "external" / "recovered"
    _existing_workspace(workspace)
    before = {
        path.relative_to(workspace): path.read_bytes()
        for path in workspace.rglob("*")
        if path.is_file()
    }

    rc = cli_main.run(
        [
            "workspace",
            "import",
            "recovered",
            "--project",
            project_dir,
            "--path",
            str(workspace),
            "--plain",
        ]
    )

    assert rc == 0
    (record,) = plain_records(capsys.readouterr().out)
    assert record["registration"] == "imported"
    assert record["status"] == "success"
    assert record["workspace"] == str(workspace.resolve())
    manifest = json.loads((Path(project_dir) / "project.json").read_text())
    (entry,) = manifest["workspaces"]
    assert entry["workspace_id"] == "recovered"
    assert entry["workspace_path"] == str(workspace.resolve())
    assert entry["start_step"] == "Synth"
    assert entry["end_step"] == "Synth"
    assert entry["parameter_patch"]["frequency_max"] == {"from": 100.0, "to": 125}
    assert entry["parameter_patch"]["max_fanout"] == {"from": None, "to": 16}
    after = {
        path.relative_to(workspace): path.read_bytes()
        for path in workspace.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_import_is_idempotent_and_external_workspace_resolves_by_id(
    tmp_path, capsys, create_cli_project, plain_records
):
    project_dir = create_cli_project()
    workspace = tmp_path / "external" / "recovered"
    _existing_workspace(workspace)
    args = [
        "workspace",
        "import",
        "recovered",
        "--project",
        project_dir,
        "--path",
        str(workspace),
        "--plain",
    ]
    assert cli_main.run(args) == 0
    capsys.readouterr()

    assert cli_main.run(args) == 0
    (record,) = [
        record for record in plain_records(capsys.readouterr().out) if "registration" in record
    ]
    assert record["registration"] == "already_registered"

    assert (
        cli_main.run(["status", "--project", project_dir, "--workspace", "recovered", "--plain"])
        == 0
    )
    records = plain_records(capsys.readouterr().out)
    assert any(record.get("workspace") == str(workspace.resolve()) for record in records)


def test_absolute_workspace_path_reuses_registered_id(
    tmp_path, capsys, create_cli_project, plain_records
):
    project_dir = create_cli_project()
    workspace = tmp_path / "external" / "directory-name"
    _existing_workspace(workspace)

    assert (
        cli_main.run(
            [
                "workspace",
                "import",
                "archive",
                "--project",
                project_dir,
                "--path",
                str(workspace),
                "--plain",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert (
        cli_main.run(
            [
                "status",
                "--project",
                project_dir,
                "--workspace",
                str(workspace),
                "--plain",
            ]
        )
        == 0
    )
    record = plain_records(capsys.readouterr().out)[0]
    assert record["workspace_id"] == "archive"
    assert record["workspace"] == str(workspace.resolve())


def test_import_rejects_invalid_workspace_without_manifest(
    tmp_path, capsys, create_cli_project, plain_records
):
    project_dir = create_cli_project()
    workspace = tmp_path / "external" / "not-a-workspace"
    workspace.mkdir(parents=True)

    rc = cli_main.run(
        [
            "workspace",
            "import",
            "bad",
            "--project",
            project_dir,
            "--path",
            str(workspace),
            "--plain",
        ]
    )

    assert rc == 1
    assert plain_records(capsys.readouterr().out)[0]["error"] == "workspace_not_importable"
    assert not (Path(project_dir) / "project.json").exists()


def test_import_rejects_design_mismatch_without_manifest(
    tmp_path, capsys, create_cli_project, plain_records
):
    project_dir = create_cli_project()
    workspace = tmp_path / "external" / "other-design"
    _existing_workspace(workspace, design="other")

    rc = cli_main.run(
        [
            "workspace",
            "import",
            "other",
            "--project",
            project_dir,
            "--path",
            str(workspace),
            "--plain",
        ]
    )

    assert rc == 1
    assert plain_records(capsys.readouterr().out)[0]["error"] == "workspace_not_importable"
    assert not (Path(project_dir) / "project.json").exists()


def test_import_rejects_id_and_path_conflicts(tmp_path, capsys, create_cli_project, plain_records):
    project_dir = create_cli_project()
    first = tmp_path / "external" / "first"
    second = tmp_path / "external" / "second"
    _existing_workspace(first)
    _existing_workspace(second)

    def invoke(workspace_id: str, path: Path) -> int:
        return cli_main.run(
            [
                "workspace",
                "import",
                workspace_id,
                "--project",
                project_dir,
                "--path",
                str(path),
                "--plain",
            ]
        )

    assert invoke("first", first) == 0
    capsys.readouterr()
    assert invoke("first", second) == 1
    assert plain_records(capsys.readouterr().out)[0]["error"] == "workspace_id_conflict"
    assert invoke("second", first) == 1
    assert plain_records(capsys.readouterr().out)[0]["error"] == "workspace_path_conflict"


def test_workspace_selector_rejects_relative_paths(
    tmp_path, capsys, create_cli_project, plain_records
):
    project_dir = create_cli_project()
    rc = cli_main.run(
        [
            "run",
            "--project",
            project_dir,
            "--workspace",
            "relative/workspace",
            "--plain",
        ]
    )
    assert rc == 1
    assert plain_records(capsys.readouterr().out)[0]["error"] == "invalid_workspace"


def test_run_creates_workspace_at_exact_external_path(
    tmp_path, capsys, create_cli_project, flow_mocks
):
    project_dir = create_cli_project()
    external_parent = tmp_path / "external"
    external_parent.mkdir()
    workspace = external_parent / "created"

    rc = cli_main.run(
        [
            "run",
            "--project",
            project_dir,
            "--workspace",
            str(workspace),
            "--plain",
        ]
    )

    assert rc == 0
    assert flow_mocks.capture["create_kwargs"]["directory"] == str(workspace.resolve())
    manifest = json.loads((Path(project_dir) / "project.json").read_text())
    assert manifest["workspaces"][0]["workspace_path"] == str(workspace.resolve())


def test_run_path_selector_registers_and_resumes_existing_external_workspace(
    tmp_path, capsys, create_cli_project, monkeypatch, plain_records
):
    project_dir = create_cli_project()
    workspace = tmp_path / "external" / "resume"
    _existing_workspace(workspace, state="Unstart")
    seen = {"ran": False, "created": False}

    from chipcompiler.engine.rerun import StepRunResult

    def spy_run_resume(flow, *, through=None):
        seen["ran"] = True
        return StepRunResult(ok=True, executed=("Synthesis",))

    class Flow:
        def __init__(self, workspace):
            self.workspace = workspace

        def create_step_workspaces(self, *, executable_steps=None):
            seen["created"] = executable_steps == {"Synthesis"}

        def load(self):
            from chipcompiler.utility import json_read

            path = self.workspace.flow.path
            if path:
                self.workspace.flow.data = json_read(path)
            return bool(self.workspace.flow.data.get("steps", []))

    monkeypatch.setattr(
        "chipcompiler.data.load_workspace",
        lambda _path: type(
            "Workspace",
            (),
            {"flow": type("FlowData", (), {"path": workspace / "home" / "flow.json"})()},
        )(),
    )
    monkeypatch.setattr("chipcompiler.engine.EngineFlow", Flow)
    monkeypatch.setattr("chipcompiler.engine.rerun.run_resume", spy_run_resume)
    monkeypatch.setattr(
        "chipcompiler.cli.project.config._validate_pdk_contents",
        lambda name, root, overrides=None: None,
    )

    rc = cli_main.run(
        [
            "run",
            "--project",
            project_dir,
            "--workspace",
            str(workspace),
            "--resume",
            "--plain",
        ]
    )

    assert rc == 0
    assert seen == {"ran": True, "created": True}
    records = plain_records(capsys.readouterr().out)
    assert any(record.get("workspace") == str(workspace.resolve()) for record in records)
    manifest = json.loads((Path(project_dir) / "project.json").read_text())
    assert manifest["workspaces"][0]["workspace_path"] == str(workspace.resolve())


def test_run_path_selector_accepts_existing_empty_target(tmp_path, create_cli_project, flow_mocks):
    project_dir = create_cli_project()
    workspace = tmp_path / "external" / "empty"
    workspace.mkdir(parents=True)

    rc = cli_main.run(
        [
            "run",
            "--project",
            project_dir,
            "--workspace",
            str(workspace),
        ]
    )

    assert rc == 0
    assert flow_mocks.capture["create_kwargs"]["directory"] == str(workspace.resolve())


def test_run_workspace_name_keeps_project_local_workspace(tmp_path, create_cli_project, flow_mocks):
    project_dir = create_cli_project()

    assert cli_main.run(["run", "--project", project_dir, "--workspace", "local"]) == 0

    assert flow_mocks.capture["create_kwargs"]["directory"] == str(Path(project_dir) / "local")
