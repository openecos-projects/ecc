import json
import os

from chipcompiler.cli import main as cli_main


class TestArtifacts:
    def test_artifacts_all_steps(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)
        create_step_dir(
            run_dir,
            "CTS",
            "ecc",
            subdirs=["output", "log"],
            files={"output/design.def": "def content", "log/cts.log": "log content"},
        )

        rc = cli_main.run(["artifacts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "cts" in out
        assert "(output)" in out
        assert "(log)" in out

    def test_artifacts_single_step(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)
        create_step_dir(
            run_dir, "CTS", "ecc", subdirs=["output"], files={"output/design.def": "def content"}
        )

        rc = cli_main.run(["artifacts", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "cts" in out
        assert "(output)" in out

    def test_artifacts_unknown_step(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(run_dir, exist_ok=True)

        rc = cli_main.run(["artifacts", "nonexistent", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "unknown_step" in out

    def test_artifacts_empty_known_step(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)
        create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"])

        rc = cli_main.run(["artifacts", "cts", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "No artifacts found" in out

    def test_artifacts_json(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)
        create_step_dir(
            run_dir, "CTS", "ecc", subdirs=["output"], files={"output/design.def": "def content"}
        )

        rc = cli_main.run(["artifacts", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "records" in data
        assert len(data["records"]) > 0
        assert data["records"][0]["artifact"] == "design.def"

    def test_artifacts_jsonl(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)
        create_step_dir(
            run_dir,
            "CTS",
            "ecc",
            subdirs=["output", "log"],
            files={"output/design.def": "def content", "log/cts.log": "log content"},
        )

        rc = cli_main.run(["artifacts", "--jsonl", "--project", project_dir])
        assert rc == 0
        objects = [json.loads(ln) for ln in capsys.readouterr().out.strip().split("\n")]
        assert len(objects) == 2
        assert all("artifact" in o for o in objects)

    def test_artifacts_with_run_id(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "sweeps", "sweep_001", "run_004")
        create_flow_json(run_dir)
        create_step_dir(
            run_dir, "CTS", "ecc", subdirs=["output"], files={"output/design.def": "def content"}
        )

        rc = cli_main.run(
            ["artifacts", "--run-id", "sweeps/sweep_001/run_004", "--project", project_dir]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "cts" in out

    def test_artifacts_derives_roles_from_dirs(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)
        create_step_dir(
            run_dir,
            "CTS",
            "ecc",
            subdirs=["config", "output", "report", "log", "analysis"],
            files={
                "config/cts_config.json": "{}",
                "output/design.def": "def",
                "report/timing.rpt": "rpt",
                "log/cts.log": "log",
                "analysis/CTS_metrics.json": "{}",
            },
        )

        rc = cli_main.run(["artifacts", "cts", "--json", "--project", project_dir])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        roles = {a["role"] for a in data["records"]}
        assert roles == {"config", "output", "report", "log", "analysis"}


class TestArtifactPaths:
    def test_nested_run_artifact_paths(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "sweeps", "sweep_001", "run_004")
        create_flow_json(run_dir)
        create_step_dir(
            run_dir, "CTS", "ecc", subdirs=["output"], files={"output/design.def": "def content"}
        )

        rc = cli_main.run(
            [
                "artifacts",
                "--run-id",
                "sweeps/sweep_001/run_004",
                "--json",
                "--project",
                project_dir,
            ]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data["records"]) == 1
        path = data["records"][0]["path"]
        assert path.startswith("sweeps/")

    def test_nested_run_step_config_paths(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_workspace_config,
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "sweeps", "sweep_001", "run_004")
        create_flow_json(run_dir)
        create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"])
        create_workspace_config(
            run_dir,
            {
                "flow_config.json": "{}",
                "db_default_config.json": "{}",
                "cts_default_config.json": "{}",
            },
        )

        rc = cli_main.run(
            [
                "config",
                "cts",
                "--resolved",
                "--run-id",
                "sweeps/sweep_001/run_004",
                "--json",
                "--project",
                project_dir,
            ]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "records" in data
        assert [item["path"] for item in data["records"]] == [
            "sweeps/sweep_001/run_004/config/flow_config.json",
            "sweeps/sweep_001/run_004/config/db_default_config.json",
            "sweeps/sweep_001/run_004/config/cts_default_config.json",
        ]
