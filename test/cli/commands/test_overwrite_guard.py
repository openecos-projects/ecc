import json
import os

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.command_handlers.project import _canonically_inside


class TestOverwriteGuard:
    def test_refuses_foreign_non_empty_dir(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        mock_pdk_validation,
        spy_mutations,
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "exp1")
        os.makedirs(run_dir)
        keep = os.path.join(run_dir, "keep.txt")
        with open(keep, "w") as f:
            f.write("precious\n")
        os.chmod(keep, 0o400)

        mutations = spy_mutations()
        rc = cli_main.run(
            ["run", "--project", project_dir, "--workspace", "exp1", "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "overwrite_refused",
                "workspace_id": "exp1",
                "workspace": run_dir,
                "reason": "target is not an ECC workspace directory",
            }
        ]
        assert mutations == {"chmod": [], "rmtree": []}
        with open(keep) as f:
            assert f.read() == "precious\n"
        assert os.stat(keep).st_mode & 0o777 == 0o400
        os.chmod(keep, 0o644)

    def test_refuses_unreadable_target_dir(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        mock_pdk_validation,
        monkeypatch,
        spy_mutations,
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "exp1")
        os.makedirs(run_dir)
        real_listdir = os.listdir

        # chmod 0o000 does not make the dir unreadable for root (CI runs as
        # root); deny the syscall itself instead.
        def denying_listdir(path):
            if os.path.normpath(path) == os.path.normpath(run_dir):
                raise PermissionError(13, "Permission denied", path)
            return real_listdir(path)

        monkeypatch.setattr(os, "listdir", denying_listdir)
        mutations = spy_mutations()

        rc = cli_main.run(
            ["run", "--project", project_dir, "--workspace", "exp1", "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "overwrite_refused",
                "workspace_id": "exp1",
                "workspace": run_dir,
                "reason": "target is not an ECC workspace directory",
            }
        ]
        assert mutations == {"chmod": [], "rmtree": []}
        assert real_listdir(run_dir) == []

    def test_refuses_symlink_target(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        mock_pdk_validation,
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        real_run = str(tmp_path / "real_run")
        create_flow_json(real_run)
        link = os.path.join(project_dir, "exp1")
        os.symlink(real_run, link)

        rc = cli_main.run(
            ["run", "--project", project_dir, "--workspace", "exp1", "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "overwrite_refused",
                "workspace_id": "exp1",
                "workspace": link,
                "reason": "target is not an ECC workspace directory",
            }
        ]
        assert os.path.islink(link)
        assert os.path.isfile(os.path.join(real_run, "home", "flow.json"))

    def test_refuses_non_directory_target(
        self, tmp_path, capsys, create_cli_project, mock_pdk_validation
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        target = os.path.join(project_dir, "exp1")
        with open(target, "w") as f:
            f.write("not a directory\n")

        rc = cli_main.run(
            ["run", "--project", project_dir, "--workspace", "exp1", "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "overwrite_refused",
                "workspace_id": "exp1",
                "workspace": target,
                "reason": "target is not an ECC workspace directory",
            }
        ]
        with open(target) as f:
            assert f.read() == "not a directory\n"

    def test_allows_empty_dir(self, tmp_path, capsys, create_cli_project, flow_mocks):
        project_dir = create_cli_project()
        run_dir = os.path.join(project_dir, "exp1")
        os.makedirs(run_dir)

        rc = cli_main.run(
            ["run", "--project", project_dir, "--workspace", "exp1", "--overwrite", "--json"]
        )

        assert rc == 0
        assert flow_mocks.capture["create_kwargs"]["directory"] == run_dir

    def test_allows_default_run_under_symlinked_project_dir(
        self, tmp_path, capsys, create_cli_project, create_flow_json, flow_mocks
    ):
        project_dir = create_cli_project()
        link = str(tmp_path / "project_link")
        os.symlink(project_dir, link)
        run_dir = os.path.join(link, "default")
        create_flow_json(run_dir, profile="main")

        rc = cli_main.run(["run", "--project", link, "--overwrite", "--json"])

        assert rc == 0
        assert flow_mocks.capture["create_kwargs"]["directory"] == run_dir

    def test_refuses_home_symlink(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        mock_pdk_validation,
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        real_run = str(tmp_path / "real_run")
        create_flow_json(real_run)
        run_dir = os.path.join(project_dir, "exp1")
        os.makedirs(run_dir)
        keep = os.path.join(run_dir, "keep.txt")
        with open(keep, "w") as f:
            f.write("precious\n")
        os.symlink(os.path.join(real_run, "home"), os.path.join(run_dir, "home"))

        rc = cli_main.run(
            ["run", "--project", project_dir, "--workspace", "exp1", "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "overwrite_refused",
                "workspace_id": "exp1",
                "workspace": run_dir,
                "reason": "target is not an ECC workspace directory",
            }
        ]
        with open(keep) as f:
            assert f.read() == "precious\n"
        assert os.path.isfile(os.path.join(real_run, "home", "flow.json"))

    def test_refuses_flow_json_symlink(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        mock_pdk_validation,
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        real_run = str(tmp_path / "real_run")
        create_flow_json(real_run)
        run_dir = os.path.join(project_dir, "exp1")
        os.makedirs(os.path.join(run_dir, "home"))
        keep = os.path.join(run_dir, "keep.txt")
        with open(keep, "w") as f:
            f.write("precious\n")
        os.symlink(
            os.path.join(real_run, "home", "flow.json"),
            os.path.join(run_dir, "home", "flow.json"),
        )

        rc = cli_main.run(
            ["run", "--project", project_dir, "--workspace", "exp1", "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "overwrite_refused",
                "workspace_id": "exp1",
                "workspace": run_dir,
                "reason": "target is not an ECC workspace directory",
            }
        ]
        with open(keep) as f:
            assert f.read() == "precious\n"
        assert os.path.isfile(os.path.join(real_run, "home", "flow.json"))

    def test_refuses_ancestor_symlink_to_empty_dir(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        mock_pdk_validation,
        spy_mutations,
    ):
        """A multi-segment target would leave the project through a symlinked
        ancestor; the workspace name is rejected before anything is touched."""
        mock_pdk_validation()
        project_dir = create_cli_project()
        victim = tmp_path / "external" / "victim"
        victim.mkdir(parents=True)
        os.symlink(str(tmp_path / "external"), os.path.join(project_dir, "sweeps"))

        mutations = spy_mutations()
        rc = cli_main.run(
            [
                "run",
                "--project",
                project_dir,
                "--workspace",
                "sweeps/victim",
                "--overwrite",
                "--json",
            ]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "invalid_workspace",
                "reason": "invalid_workspace: 'sweeps/victim' is not a single workspace name",
            }
        ]
        assert mutations == {"chmod": [], "rmtree": []}
        assert victim.is_dir()

    def test_refuses_ancestor_symlink_to_sentinel_dir(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        mock_pdk_validation,
        spy_mutations,
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        victim = tmp_path / "external" / "victim"
        create_flow_json(str(victim))
        keep = victim / "keep.txt"
        keep.write_text("precious\n")
        os.chmod(keep, 0o400)
        os.symlink(str(tmp_path / "external"), os.path.join(project_dir, "sweeps"))

        mutations = spy_mutations()
        rc = cli_main.run(
            [
                "run",
                "--project",
                project_dir,
                "--workspace",
                "sweeps/victim",
                "--overwrite",
                "--json",
            ]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "invalid_workspace",
                "reason": "invalid_workspace: 'sweeps/victim' is not a single workspace name",
            }
        ]
        assert mutations == {"chmod": [], "rmtree": []}
        assert keep.read_text() == "precious\n"
        assert os.stat(keep).st_mode & 0o777 == 0o400
        assert (victim / "home" / "flow.json").is_file()
        os.chmod(keep, 0o644)

    def test_refuses_dotdot_after_symlink_component(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        mock_pdk_validation,
        spy_mutations,
    ):
        """A ".." after a symlink component would reach a victim outside the
        project; the multi-segment spelling is rejected as a workspace name."""
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
        mutations = spy_mutations()
        rc = cli_main.run(
            ["run", "--project", project_dir, "--workspace", run_id, "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "invalid_workspace",
                "reason": f"invalid_workspace: {run_id!r} is not a single workspace name",
            }
        ]
        assert mutations == {"chmod": [], "rmtree": []}
        assert keep.read_text() == "precious\n"
        assert os.stat(keep).st_mode & 0o777 == 0o400
        assert (victim / "home" / "flow.json").is_file()
        os.chmod(keep, 0o644)

    def test_refuses_dotdot_escape_through_symlinked_project_dir(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        mock_pdk_validation,
        spy_mutations,
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
        mutations = spy_mutations()
        rc = cli_main.run(
            ["run", "--project", link, "--workspace", run_id, "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "invalid_workspace",
                "reason": f"invalid_workspace: {run_id!r} is not a single workspace name",
            }
        ]
        assert mutations == {"chmod": [], "rmtree": []}
        assert keep.read_text() == "precious\n"
        assert os.stat(keep).st_mode & 0o777 == 0o400
        os.chmod(keep, 0o644)


class TestCanonicallyInside:
    def test_root_anchor_contains_everything(self):
        assert _canonically_inside("/tmp/x", "/")
        assert _canonically_inside("/", "/")

    def test_sibling_is_outside(self, tmp_path):
        anchor = tmp_path / "project"
        anchor.mkdir()
        assert not _canonically_inside(str(tmp_path / "other"), str(anchor))
