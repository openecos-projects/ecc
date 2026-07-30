import json
import os

import pytest

from chipcompiler.cli import main as cli_main


class TestStepConfigInvalidFlowRun:
    @pytest.mark.parametrize("run_id", ("default", ""))
    @pytest.mark.parametrize(
        ("toml_line", "reason"),
        [
            ('run = ""', "unsupported flow.run: "),
            ("run = 42", "unsupported flow.run: 42"),
        ],
    )
    def test_step_config_errors_on_invalid_flow_run_with_selector(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        create_step_dir,
        set_flow_run,
        toml_line,
        reason,
        run_id,
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, toml_line)
        run_dir = os.path.join(project_dir, "runs", "default")
        create_flow_json(run_dir)
        create_step_dir(run_dir, "CTS", "ecc", subdirs=["output"])

        rc = cli_main.run(
            ["config", "cts", "--resolved", "--run-id", run_id, "--project", project_dir, "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "config_error",
                "reason": reason,
                "inspect": f"ecc check --project {project_dir}",
            }
        ]


class TestConfigUnreadableFallback:
    def test_config_resolved_reports_invalid_config_on_unreadable_toml(
        self, tmp_path, capsys, create_cli_project, monkeypatch
    ):
        project_dir = create_cli_project()

        def deny(config_path):
            raise PermissionError(13, "Permission denied", config_path)

        monkeypatch.setattr("chipcompiler.cli.project.config.load_project_config", deny)

        rc = cli_main.run(["config", "--resolved", "--project", project_dir, "--json"])

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

        rc = cli_main.run(["config", "--resolved", "--project", project_dir, "--json"])

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "invalid_config",
                "inspect": f"ecc check --project {project_dir}",
            }
        ]
