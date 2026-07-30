from chipcompiler.cli.project.config import config_run_id


class TestConfigRunId:
    def test_unreadable_config_returns_none(self, create_cli_project, monkeypatch):
        project_dir = create_cli_project()

        def deny(config_path):
            raise PermissionError(13, "Permission denied", config_path)

        monkeypatch.setattr("chipcompiler.cli.project.config.load_project_config", deny)

        assert config_run_id(project_dir) is None
