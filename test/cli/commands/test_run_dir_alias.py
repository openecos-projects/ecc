import json
import os

import pytest

from chipcompiler.cli import main as cli_main


class TestRunDirAliasRefusal:
    @pytest.mark.parametrize(
        ("run_id", "workspace"),
        [
            (".", os.path.join("runs", ".")),
            ("..", os.path.join("runs", "..")),
            ("runs/default/..", os.path.join("runs", "default", "..")),
        ],
    )
    def test_aliasing_run_id_refused(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        mock_pdk_validation,
        run_id,
        workspace,
        legacy_hint,
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
        marker = os.path.join(project_dir, "runs", "other_run")
        os.makedirs(marker)

        rc = cli_main.run(
            ["run", "--project", project_dir, "--run-id", run_id, "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "invalid_run_id",
                "run": run_id,
                "workspace": os.path.join(project_dir, workspace),
                "reason": "run id must not resolve to the project or runs container",
            },
            legacy_hint(project_dir),
        ]
        assert os.path.isdir(marker)

    def test_absolute_project_dir_run_id_refused(
        self, tmp_path, capsys, create_cli_project, mock_pdk_validation, legacy_hint
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", project_dir, "--json"])

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "invalid_run_id",
                "run": project_dir,
                "workspace": project_dir,
                "reason": "run id must not resolve to the project or runs container",
            },
            legacy_hint(project_dir),
        ]

    def test_configured_dotdot_run_refused(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        set_flow_run,
        mock_pdk_validation,
        legacy_hint,
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
        set_flow_run(project_dir, 'run = ".."')

        rc = cli_main.run(["run", "--project", project_dir, "--overwrite", "--json"])

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "invalid_run_id",
                "run": "..",
                "workspace": os.path.join(project_dir, "runs", ".."),
                "reason": "run id must not resolve to the project or runs container",
            },
            legacy_hint(project_dir),
        ]

    def test_symlink_spelling_of_runs_container_refused(
        self, tmp_path, capsys, create_cli_project, mock_pdk_validation, legacy_hint
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
        os.symlink(os.path.join(project_dir, "runs"), os.path.join(project_dir, "runs", "sneaky"))
        marker = os.path.join(project_dir, "runs", "other_run")
        os.makedirs(marker)

        rc = cli_main.run(
            ["run", "--project", project_dir, "--run-id", "sneaky", "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "invalid_run_id",
                "run": "sneaky",
                "workspace": os.path.join(project_dir, "runs", "sneaky"),
                "reason": "run id must not resolve to the project or runs container",
            },
            legacy_hint(project_dir),
        ]
        assert os.path.isdir(marker)

    def test_symlink_spelling_of_project_dir_refused(
        self, tmp_path, capsys, create_cli_project, mock_pdk_validation, legacy_hint
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
        link = str(tmp_path / "project_link")
        os.symlink(project_dir, link)

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", link, "--json"])

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "invalid_run_id",
                "run": link,
                "workspace": link,
                "reason": "run id must not resolve to the project or runs container",
            },
            legacy_hint(project_dir),
        ]
