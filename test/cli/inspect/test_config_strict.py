import json
import os

import pytest

from chipcompiler.cli import main as cli_main


class TestStepConfigIgnoresLegacyFlowRun:
    @pytest.mark.parametrize("selector", ("default", None))
    @pytest.mark.parametrize("toml_line", ('run = ""', "run = 42"))
    def test_step_config_ignores_legacy_flow_run_with_selector(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        create_cts_workspace_config,
        set_flow_run,
        toml_line,
        selector,
    ):
        """The step view reads only the workspace; a legacy [flow].run key
        in ecc.toml must not break step-scoped config listing."""
        project_dir = create_cli_project()
        set_flow_run(project_dir, toml_line)
        run_dir = os.path.join(project_dir, "default")
        create_flow_json(run_dir)
        create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"])
        create_cts_workspace_config(run_dir)

        args = ["config", "cts"]
        if selector is not None:
            args += ["--workspace", selector]
        args += ["--project", project_dir, "--json"]
        rc = cli_main.run(args)

        assert rc == 0
        records = json.loads(capsys.readouterr().out)["records"]
        assert [item["path"] for item in records] == [
            "default/config/db_ecc.json",
            "default/config/cts_ecc.json",
        ]


class TestConfigUnreadableFallback:
    def test_config_resolved_reports_invalid_config_on_unreadable_toml(
        self, tmp_path, capsys, create_cli_project, monkeypatch
    ):
        project_dir = create_cli_project()

        def deny(config_path):
            raise PermissionError(13, "Permission denied", config_path)

        monkeypatch.setattr("chipcompiler.cli.project.config.load_project_config", deny)

        rc = cli_main.run(["config", "--project", project_dir, "--json"])

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "invalid_config",
                "inspect": f"ecc check --project {project_dir}",
            }
        ]

    def test_config_resolved_reports_invalid_config_on_non_utf8_toml(
        self, tmp_path, capsys, create_cli_project
    ):
        project_dir = create_cli_project()
        with open(os.path.join(project_dir, "ecc.toml"), "wb") as f:
            f.write(b'[flow]\nrun = "\xff\xfe"\n')

        rc = cli_main.run(["config", "--project", project_dir, "--json"])

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "invalid_config",
                "inspect": f"ecc check --project {project_dir}",
            }
        ]
