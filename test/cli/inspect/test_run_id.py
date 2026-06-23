import json
import os

from chipcompiler.cli import main as cli_main


class TestRunIdResolution:
    def test_status_default_run_id(self, tmp_path, capsys, create_cli_project, create_flow_json):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)

        rc = cli_main.run(["status", "--run-id", "default", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "default" in out

    def test_status_simple_token_run_id(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "run_004")
        os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
        create_flow_json(run_dir)

        rc = cli_main.run(["status", "--run-id", "run_004", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "run_004" in out

    def test_status_relative_path_run_id(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "sweeps", "sweep_001", "run_004")
        create_flow_json(run_dir)

        rc = cli_main.run(
            ["status", "--run-id", "sweeps/sweep_001/run_004", "--project", project_dir]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "sweeps/sweep_001/run_004" in out

    def test_status_absolute_path_run_id(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = tmp_path / "ecc-run-004"
        create_flow_json(str(run_dir))

        rc = cli_main.run(["status", "--run-id", str(run_dir), "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "run:" in out

    def test_status_missing_run_id(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()

        rc = cli_main.run(["status", "--run-id", "nonexistent", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "missing" in out

    def test_log_preserves_run_id(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "run_005")
        create_flow_json(run_dir)
        create_step_dir(
            run_dir,
            "Synthesis",
            "yosys",
            subdirs=["log"],
            files={"log/synthesis.log": "Error: something failed\n"},
        )

        rc = cli_main.run(
            ["log", "synthesis", "--errors", "--run-id", "run_005", "--project", project_dir]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "--run-id run_005" in out

    def test_metrics_preserves_run_id(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "run_006")
        create_flow_json(
            run_dir,
            [
                {"name": "CTS", "tool": "ecc", "state": "Success", "runtime": "0:00:04"},
            ],
        )
        create_step_dir(
            run_dir,
            "CTS",
            "ecc",
            subdirs=["analysis"],
            files={"analysis/CTS_metrics.json": json.dumps({"Frequency [MHz]": 450.0})},
        )

        rc = cli_main.run(["metrics", "cts", "--run-id", "run_006", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "--run-id run_006" in out


class TestRunIdDisclosure:
    def test_explicit_default_preserved_in_disclosure(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)

        rc = cli_main.run(["status", "--run-id", "default", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "--run-id default" in out

    def test_project_relative_run_id_resolves(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "sweeps", "sweep_001", "run_004")
        create_flow_json(run_dir)

        rc = cli_main.run(
            ["status", "--run-id", "sweeps/sweep_001/run_004", "--project", project_dir]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "sweeps/sweep_001/run_004" in out


class TestCorruptFlowJson:
    def test_corrupt_flow_json_status_reports_corrupt(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
        with open(os.path.join(run_dir, "home", "flow.json"), "w") as f:
            f.write("BROKEN{{{")
        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "corrupt" in out

    def test_missing_flow_json_status_reports_missing(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(run_dir, exist_ok=True)
        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "missing" in out

    def test_corrupt_flow_json_json_reports_corrupt(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
        with open(os.path.join(run_dir, "home", "flow.json"), "w") as f:
            f.write("BROKEN{{{")
        rc = cli_main.run(["status", "--json", "--project", project_dir])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["status"] == "corrupt"


class TestMissingRunJsonlKind:
    def test_missing_run_jsonl_has_kind(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(run_dir, exist_ok=True)

        rc = cli_main.run(["status", "--jsonl", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        data = [json.loads(line) for line in out.strip().split("\n") if line.strip()]
        assert data[0]["run"] == "default"
        assert data[0]["status"] == "missing"
