import os

from chipcompiler.cli import main as cli_main


class TestReadOnly:
    def test_artifacts_does_not_modify_files(
        self, tmp_path, capsys, create_cli_project, create_flow_json, create_step_dir
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)
        create_step_dir(
            run_dir, "CTS", "ecc", subdirs=["output"], files={"output/design.def": "original"}
        )

        before_mtime = os.path.getmtime(os.path.join(run_dir, "CTS_ecc", "output", "design.def"))

        rc = cli_main.run(["artifacts", "--project", project_dir])
        assert rc == 0

        after_mtime = os.path.getmtime(os.path.join(run_dir, "CTS_ecc", "output", "design.def"))
        assert before_mtime == after_mtime

    def test_no_persistent_metadata_files(
        self,
        tmp_path,
        capsys,
        monkeypatch,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        mock_pdk_validation,
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)
        create_step_dir(
            run_dir, "CTS", "ecc", subdirs=["output"], files={"output/design.def": "def content"}
        )

        cli_main.run(["artifacts", "--project", project_dir])
        cli_main.run(["config", "--resolved", "--project", project_dir])
        cli_main.run(["diagnose", "--project", project_dir])

        assert not os.path.exists(os.path.join(project_dir, "issues.json"))
        assert not os.path.exists(os.path.join(project_dir, "artifacts.json"))
        assert not os.path.exists(os.path.join(project_dir, "resolved_config.json"))
        assert not os.path.exists(os.path.join(run_dir, "issues.json"))
        assert not os.path.exists(os.path.join(run_dir, "artifacts.json"))
