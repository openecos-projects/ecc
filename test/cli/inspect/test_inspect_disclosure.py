import os

from chipcompiler.cli import main as cli_main


class TestDisclosure:
    def test_artifacts_lines_have_disclosure(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        has_disclosure,
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
        assert has_disclosure(out)

    def test_config_resolved_lines_have_disclosure(
        self, tmp_path, capsys, monkeypatch, create_cli_project, mock_pdk_validation, has_disclosure
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()

        rc = cli_main.run(["config", "--resolved", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert has_disclosure(out)

    def test_diagnose_lines_have_disclosure(
        self, tmp_path, capsys, create_cli_project, has_disclosure
    ):
        project_dir = create_cli_project()

        rc = cli_main.run(["diagnose", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert has_disclosure(out)

    def test_phase2_disclosure_preserves_run_id(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "run_008")
        create_flow_json(
            run_dir,
            [
                {"name": "CTS", "tool": "ecc", "state": "Incomplete", "runtime": "0:00:04"},
            ],
        )
        create_step_dir(
            run_dir, "CTS", "ecc", subdirs=["log"], files={"log/cts.log": "Error: fail\n"}
        )

        rc = cli_main.run(["diagnose", "--run-id", "run_008", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "--run-id run_008" in out

    def test_artifacts_disclosure_preserves_project(
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
        assert f"--project {project_dir}" in out
