import os

from chipcompiler.cli import main as cli_main


class TestReadOnly:
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

        cli_main.run(["config", "--project", project_dir])

        assert not os.path.exists(os.path.join(project_dir, "resolved_config.json"))
