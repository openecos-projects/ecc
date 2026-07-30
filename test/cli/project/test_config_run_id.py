import os

from chipcompiler.cli.project.config import config_run_id


class TestConfigRunId:
    def test_unreadable_config_returns_none(self, create_cli_project, monkeypatch):
        project_dir = create_cli_project()

        def deny(config_path):
            raise PermissionError(13, "Permission denied", config_path)

        monkeypatch.setattr("chipcompiler.cli.project.config.load_project_config", deny)

        assert config_run_id(project_dir) is None

    def test_non_utf8_config_returns_none(self, create_cli_project):
        project_dir = create_cli_project()
        with open(os.path.join(project_dir, "ecc.toml"), "wb") as f:
            f.write(b'[flow]\nrun = "\xff\xfe"\n')

        assert config_run_id(project_dir) is None
