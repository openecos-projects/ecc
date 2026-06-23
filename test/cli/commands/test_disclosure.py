import json
import os

from chipcompiler.cli import main as cli_main


class TestDisclosureCommands:
    def test_init_lines_have_disclosure(self, tmp_path, capsys, has_disclosure):
        project_path = str(tmp_path / "disctest")
        rc = cli_main.run(["init", project_path])
        assert rc == 0
        out = capsys.readouterr().out
        assert has_disclosure(out)

    def test_check_lines_have_disclosure(
        self, tmp_path, monkeypatch, capsys, create_cli_project, has_disclosure
    ):
        project_dir = create_cli_project()
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root: None,
        )
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert has_disclosure(out)

    def test_status_lines_have_disclosure(
        self, tmp_path, capsys, create_cli_project, create_flow_json, has_disclosure
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir, profile="main")

        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert has_disclosure(out)

    def test_metrics_lines_have_disclosure(
        self, tmp_path, capsys, create_cli_project, has_disclosure
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")

        analysis_dir = os.path.join(run_dir, "Synthesis_yosys", "analysis")
        os.makedirs(analysis_dir, exist_ok=True)
        with open(os.path.join(analysis_dir, "Synthesis_metrics.json"), "w") as f:
            json.dump({"Cell number": 312}, f)

        rc = cli_main.run(["metrics", "synthesis", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert has_disclosure(out)

    def test_log_error_lines_have_disclosure(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")

        step_dir = os.path.join(run_dir, "Synthesis_yosys", "log")
        os.makedirs(step_dir, exist_ok=True)
        with open(os.path.join(step_dir, "synthesis.log"), "w") as f:
            f.write("Error: something failed\n")

        rc = cli_main.run(["log", "synthesis", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "ecc log synthesis" in out

    def test_project_arg_propagated_to_disclosure(
        self, tmp_path, capsys, create_cli_project, create_flow_json
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir, profile="main")

        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert f"--project {project_dir}" in out

    def test_output_lowercase_tokens(self, tmp_path, capsys, create_cli_project, create_flow_json):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(
            run_dir,
            [
                {"name": "Synthesis", "tool": "yosys", "state": "Success", "runtime": "0:00:01"},
            ],
        )

        rc = cli_main.run(["status", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "synthesis" in out
        assert "success" in out
