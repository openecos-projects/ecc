import json
import os

import pytest

from chipcompiler.cli import main as cli_main


class TestRunDirectory:
    def test_run_id_bare_name_writes_under_runs(
        self, tmp_path, capsys, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", "exp1", "--json"])

        assert rc == 0
        run_dir = os.path.join(project_dir, "runs", "exp1")
        assert flow_mocks.capture["create_kwargs"]["directory"] == run_dir
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "run": "exp1",
                "status": "success",
                "workspace": run_dir,
                "inspect_cmd": f"ecc status --project {project_dir} --run-id exp1",
                "log_cmd": f"ecc log --project {project_dir} --run-id exp1",
            }
        ]

    def test_run_id_relative_path_writes_project_relative(
        self, tmp_path, capsys, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", "sweeps/s1/r4", "--json"])

        assert rc == 0
        run_dir = os.path.join(project_dir, "sweeps", "s1", "r4")
        assert flow_mocks.capture["create_kwargs"]["directory"] == run_dir
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "run": "sweeps/s1/r4",
                "status": "success",
                "workspace": run_dir,
                "inspect_cmd": f"ecc status --project {project_dir} --run-id sweeps/s1/r4",
                "log_cmd": f"ecc log --project {project_dir} --run-id sweeps/s1/r4",
            }
        ]

    def test_run_id_absolute_path_writes_verbatim(
        self, tmp_path, capsys, create_cli_project, flow_mocks
    ):
        project_dir = create_cli_project()
        abs_run = str(tmp_path / "abs_run")

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", abs_run, "--json"])

        assert rc == 0
        assert flow_mocks.capture["create_kwargs"]["directory"] == abs_run
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "run": abs_run,
                "status": "success",
                "workspace": abs_run,
                "inspect_cmd": f"ecc status --project {project_dir} --run-id {abs_run}",
                "log_cmd": f"ecc log --project {project_dir} --run-id {abs_run}",
            }
        ]

    def test_configured_flow_run_writes_there(
        self, tmp_path, capsys, create_cli_project, set_flow_run, flow_mocks
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = "exp1"')

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc == 0
        run_dir = os.path.join(project_dir, "runs", "exp1")
        assert flow_mocks.capture["create_kwargs"]["directory"] == run_dir
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "run": "exp1",
                "status": "success",
                "workspace": run_dir,
                "inspect_cmd": f"ecc status --project {project_dir} --run-id exp1",
                "log_cmd": f"ecc log --project {project_dir} --run-id exp1",
            }
        ]

    def test_run_id_overrides_configured_flow_run(
        self, tmp_path, capsys, create_cli_project, set_flow_run, flow_mocks
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = "exp1"')

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", "other", "--json"])

        assert rc == 0
        run_dir = os.path.join(project_dir, "runs", "other")
        assert flow_mocks.capture["create_kwargs"]["directory"] == run_dir
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "run": "other",
                "status": "success",
                "workspace": run_dir,
                "inspect_cmd": f"ecc status --project {project_dir} --run-id other",
                "log_cmd": f"ecc log --project {project_dir} --run-id other",
            }
        ]

    def test_absent_flow_run_key_matches_default_records(
        self, tmp_path, capsys, create_cli_project, set_flow_run, flow_mocks
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, None)

        rc = cli_main.run(["run", "--project", project_dir, "--json"])

        assert rc == 0
        run_dir = os.path.join(project_dir, "runs", "default")
        assert flow_mocks.capture["create_kwargs"]["directory"] == run_dir
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "run": "default",
                "status": "success",
                "workspace": run_dir,
                "inspect_cmd": f"ecc status --project {project_dir}",
                "log_cmd": f"ecc log --project {project_dir}",
            }
        ]

    def test_run_exists_for_named_run(
        self, tmp_path, capsys, create_cli_project, create_flow_json, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "exp1")
        create_flow_json(run_dir)

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", "exp1", "--json"])

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "run_exists",
                "run": "exp1",
                "workspace": run_dir,
                "overwrite": f"ecc run --overwrite --project {project_dir} --run-id exp1",
            }
        ]

    def test_overwrite_rebuilds_named_run(
        self, tmp_path, capsys, create_cli_project, create_flow_json, flow_mocks
    ):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "exp1")
        create_flow_json(run_dir, profile="main")

        rc = cli_main.run(
            ["run", "--project", project_dir, "--run-id", "exp1", "--overwrite", "--json"]
        )

        assert rc == 0
        assert flow_mocks.capture["create_kwargs"]["directory"] == run_dir
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "run": "exp1",
                "status": "success",
                "workspace": run_dir,
                "inspect_cmd": f"ecc status --project {project_dir} --run-id exp1",
                "log_cmd": f"ecc log --project {project_dir} --run-id exp1",
            }
        ]


class TestOverwriteGuard:
    def test_refuses_foreign_non_empty_dir(
        self, tmp_path, capsys, create_cli_project, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "exp1")
        os.makedirs(run_dir)
        keep = os.path.join(run_dir, "keep.txt")
        with open(keep, "w") as f:
            f.write("precious\n")
        os.chmod(keep, 0o400)

        rc = cli_main.run(
            ["run", "--project", project_dir, "--run-id", "exp1", "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "overwrite_refused",
                "run": "exp1",
                "workspace": run_dir,
                "reason": "target is not an ECC run directory",
            }
        ]
        with open(keep) as f:
            assert f.read() == "precious\n"
        assert os.stat(keep).st_mode & 0o777 == 0o400
        os.chmod(keep, 0o644)

    def test_refuses_symlink_target(
        self, tmp_path, capsys, create_cli_project, create_flow_json, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        real_run = str(tmp_path / "real_run")
        create_flow_json(real_run)
        link = os.path.join(project_dir, "runs", "exp1")
        os.symlink(real_run, link)

        rc = cli_main.run(
            ["run", "--project", project_dir, "--run-id", "exp1", "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "overwrite_refused",
                "run": "exp1",
                "workspace": link,
                "reason": "target is not an ECC run directory",
            }
        ]
        assert os.path.islink(link)
        assert os.path.isfile(os.path.join(real_run, "home", "flow.json"))

    def test_refuses_non_directory_target(
        self, tmp_path, capsys, create_cli_project, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        target = os.path.join(project_dir, "runs", "exp1")
        with open(target, "w") as f:
            f.write("not a directory\n")

        rc = cli_main.run(
            ["run", "--project", project_dir, "--run-id", "exp1", "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "overwrite_refused",
                "run": "exp1",
                "workspace": target,
                "reason": "target is not an ECC run directory",
            }
        ]
        with open(target) as f:
            assert f.read() == "not a directory\n"

    def test_allows_empty_dir(self, tmp_path, capsys, create_cli_project, flow_mocks):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "runs", "exp1")
        os.makedirs(run_dir)

        rc = cli_main.run(
            ["run", "--project", project_dir, "--run-id", "exp1", "--overwrite", "--json"]
        )

        assert rc == 0
        assert flow_mocks.capture["create_kwargs"]["directory"] == run_dir

    def test_allows_default_run_under_symlinked_project_dir(
        self, tmp_path, capsys, create_cli_project, create_flow_json, flow_mocks
    ):
        project_dir = create_cli_project()
        link = str(tmp_path / "project_link")
        os.symlink(project_dir, link)
        run_dir = os.path.join(link, "runs", "default")
        create_flow_json(run_dir, profile="main")

        rc = cli_main.run(["run", "--project", link, "--overwrite", "--json"])

        assert rc == 0
        assert flow_mocks.capture["create_kwargs"]["directory"] == run_dir

    def test_refuses_home_symlink(
        self, tmp_path, capsys, create_cli_project, create_flow_json, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        real_run = str(tmp_path / "real_run")
        create_flow_json(real_run)
        run_dir = os.path.join(project_dir, "runs", "exp1")
        os.makedirs(run_dir)
        keep = os.path.join(run_dir, "keep.txt")
        with open(keep, "w") as f:
            f.write("precious\n")
        os.symlink(os.path.join(real_run, "home"), os.path.join(run_dir, "home"))

        rc = cli_main.run(
            ["run", "--project", project_dir, "--run-id", "exp1", "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "overwrite_refused",
                "run": "exp1",
                "workspace": run_dir,
                "reason": "target is not an ECC run directory",
            }
        ]
        with open(keep) as f:
            assert f.read() == "precious\n"
        assert os.path.isfile(os.path.join(real_run, "home", "flow.json"))

    def test_refuses_flow_json_symlink(
        self, tmp_path, capsys, create_cli_project, create_flow_json, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        real_run = str(tmp_path / "real_run")
        create_flow_json(real_run)
        run_dir = os.path.join(project_dir, "runs", "exp1")
        os.makedirs(os.path.join(run_dir, "home"))
        keep = os.path.join(run_dir, "keep.txt")
        with open(keep, "w") as f:
            f.write("precious\n")
        os.symlink(
            os.path.join(real_run, "home", "flow.json"),
            os.path.join(run_dir, "home", "flow.json"),
        )

        rc = cli_main.run(
            ["run", "--project", project_dir, "--run-id", "exp1", "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "overwrite_refused",
                "run": "exp1",
                "workspace": run_dir,
                "reason": "target is not an ECC run directory",
            }
        ]
        with open(keep) as f:
            assert f.read() == "precious\n"
        assert os.path.isfile(os.path.join(real_run, "home", "flow.json"))

    def test_refuses_ancestor_symlink_to_empty_dir(
        self, tmp_path, capsys, create_cli_project, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        victim = tmp_path / "external" / "victim"
        victim.mkdir(parents=True)
        os.symlink(str(tmp_path / "external"), os.path.join(project_dir, "sweeps"))

        rc = cli_main.run(
            [
                "run",
                "--project",
                project_dir,
                "--run-id",
                "sweeps/victim",
                "--overwrite",
                "--json",
            ]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "overwrite_refused",
                "run": "sweeps/victim",
                "workspace": os.path.join(project_dir, "sweeps", "victim"),
                "reason": "target is not an ECC run directory",
            }
        ]
        assert victim.is_dir()

    def test_refuses_ancestor_symlink_to_sentinel_dir(
        self, tmp_path, capsys, create_cli_project, create_flow_json, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        victim = tmp_path / "external" / "victim"
        create_flow_json(str(victim))
        keep = victim / "keep.txt"
        keep.write_text("precious\n")
        os.chmod(keep, 0o400)
        os.symlink(str(tmp_path / "external"), os.path.join(project_dir, "sweeps"))

        rc = cli_main.run(
            [
                "run",
                "--project",
                project_dir,
                "--run-id",
                "sweeps/victim",
                "--overwrite",
                "--json",
            ]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "overwrite_refused",
                "run": "sweeps/victim",
                "workspace": os.path.join(project_dir, "sweeps", "victim"),
                "reason": "target is not an ECC run directory",
            }
        ]
        assert keep.read_text() == "precious\n"
        assert os.stat(keep).st_mode & 0o777 == 0o400
        assert (victim / "home" / "flow.json").is_file()
        os.chmod(keep, 0o644)

    def test_refuses_dotdot_after_symlink_component(
        self, tmp_path, capsys, create_cli_project, create_flow_json, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        child = tmp_path / "outside" / "child"
        child.mkdir(parents=True)
        victim = tmp_path / "outside" / "victim"
        create_flow_json(str(victim))
        keep = victim / "keep.txt"
        keep.write_text("precious\n")
        os.chmod(keep, 0o400)
        os.makedirs(os.path.join(project_dir, "sweeps"))
        os.symlink(str(child), os.path.join(project_dir, "sweeps", "jump"))

        run_id = os.path.join("sweeps", "jump", "..", "victim")
        rc = cli_main.run(
            ["run", "--project", project_dir, "--run-id", run_id, "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "overwrite_refused",
                "run": run_id,
                "workspace": os.path.join(project_dir, run_id),
                "reason": "target is not an ECC run directory",
            }
        ]
        assert keep.read_text() == "precious\n"
        assert os.stat(keep).st_mode & 0o777 == 0o400
        assert (victim / "home" / "flow.json").is_file()
        os.chmod(keep, 0o644)

    def test_refuses_dotdot_escape_through_symlinked_project_dir(
        self, tmp_path, capsys, create_cli_project, create_flow_json, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        link_dir = tmp_path / "link_dir"
        link_dir.mkdir()
        link = str(link_dir / "project_link")
        os.symlink(project_dir, link)
        victim = tmp_path / "victim"
        create_flow_json(str(victim))
        keep = victim / "keep.txt"
        keep.write_text("precious\n")
        os.chmod(keep, 0o400)

        run_id = os.path.join("..", "victim")
        rc = cli_main.run(["run", "--project", link, "--run-id", run_id, "--overwrite", "--json"])

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "overwrite_refused",
                "run": run_id,
                "workspace": os.path.join(link, "..", "victim"),
                "reason": "target is not an ECC run directory",
            }
        ]
        assert keep.read_text() == "precious\n"
        assert os.stat(keep).st_mode & 0o777 == 0o400
        os.chmod(keep, 0o644)


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
        self, tmp_path, capsys, create_cli_project, mock_pdk_validation, run_id, workspace
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
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
            }
        ]
        assert os.path.isdir(marker)

    def test_absolute_project_dir_run_id_refused(
        self, tmp_path, capsys, create_cli_project, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", project_dir, "--json"])

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "invalid_run_id",
                "run": project_dir,
                "workspace": project_dir,
                "reason": "run id must not resolve to the project or runs container",
            }
        ]

    def test_configured_dotdot_run_refused(
        self, tmp_path, capsys, create_cli_project, set_flow_run, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
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
            }
        ]

    def test_symlink_spelling_of_runs_container_refused(
        self, tmp_path, capsys, create_cli_project, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
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
            }
        ]
        assert os.path.isdir(marker)

    def test_symlink_spelling_of_project_dir_refused(
        self, tmp_path, capsys, create_cli_project, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
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
            }
        ]
