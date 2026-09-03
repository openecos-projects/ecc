import json
import os

from chipcompiler.cli import main as cli_main


def _failing_create_workspace(**kwargs):
    os.makedirs(os.path.join(kwargs["directory"], "home"))
    raise RuntimeError("rtl copy failed")


class TestPartialWorkspaceRecovery:
    def test_failed_creation_removes_fresh_target(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        mock_pdk_validation,
        monkeypatch,
        legacy_hint,
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
        run_dir = os.path.join(project_dir, "runs", "exp1")
        monkeypatch.setattr("chipcompiler.data.create_workspace", _failing_create_workspace)

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", "exp1", "--json"])

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "workspace_failed",
                "run": "exp1",
                "workspace": run_dir,
                "reason": "rtl copy failed",
            },
            legacy_hint(project_dir),
        ]
        assert not os.path.lexists(run_dir)

    def test_existing_dir_without_overwrite_preserves_content(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        mock_pdk_validation,
        spy_mutations,
        legacy_hint,
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
        run_dir = os.path.join(project_dir, "runs", "exp1")
        os.makedirs(run_dir)
        keep = os.path.join(run_dir, "keep.txt")
        with open(keep, "w") as f:
            f.write("precious\n")
        mutations = spy_mutations()

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", "exp1", "--json"])

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "run_exists",
                "run": "exp1",
                "workspace": run_dir,
                "overwrite": f"ecc run --overwrite --project {project_dir} --run-id exp1",
            },
            legacy_hint(project_dir),
        ]
        assert mutations == {"chmod": [], "rmtree": []}
        with open(keep) as f:
            assert f.read() == "precious\n"

    def test_failed_creation_after_overwrite_removes_partial(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        create_flow_json,
        mock_pdk_validation,
        monkeypatch,
        legacy_hint,
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
        run_dir = os.path.join(project_dir, "runs", "exp1")
        create_flow_json(run_dir)
        monkeypatch.setattr("chipcompiler.data.create_workspace", _failing_create_workspace)

        rc = cli_main.run(
            ["run", "--project", project_dir, "--run-id", "exp1", "--overwrite", "--json"]
        )

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "workspace_failed",
                "run": "exp1",
                "workspace": run_dir,
                "reason": "rtl copy failed",
            },
            legacy_hint(project_dir),
        ]
        assert not os.path.lexists(run_dir)

    def test_lost_ownership_race_preserves_active_workspace(
        self,
        tmp_path,
        capsys,
        create_cli_project,
        mock_pdk_validation,
        spy_mutations,
        legacy_hint,
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
        run_dir = os.path.join(project_dir, "runs", "exp1")
        # A concurrent run won the target and is mid-population: this
        # process loses the atomic create and must stop before writing.
        os.makedirs(os.path.join(run_dir, "home"))
        mutations = spy_mutations()

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", "exp1", "--json"])

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "run_exists",
                "run": "exp1",
                "workspace": run_dir,
                "overwrite": f"ecc run --overwrite --project {project_dir} --run-id exp1",
            },
            legacy_hint(project_dir),
        ]
        assert mutations["rmtree"] == []
        assert os.path.isdir(os.path.join(run_dir, "home"))

    def test_empty_dir_without_overwrite_reports_run_exists(
        self, tmp_path, capsys, create_cli_project, mock_pdk_validation, legacy_hint
    ):
        mock_pdk_validation()
        project_dir = create_cli_project()
        os.makedirs(os.path.join(project_dir, "runs", ".keep"), exist_ok=True)
        run_dir = os.path.join(project_dir, "runs", "exp1")
        os.makedirs(run_dir)

        rc = cli_main.run(["run", "--project", project_dir, "--run-id", "exp1", "--json"])

        assert rc == 1
        assert json.loads(capsys.readouterr().out)["records"] == [
            {
                "kind": "error",
                "error": "run_exists",
                "run": "exp1",
                "workspace": run_dir,
                "overwrite": f"ecc run --overwrite --project {project_dir} --run-id exp1",
            },
            legacy_hint(project_dir),
        ]
        assert os.listdir(run_dir) == []

    def test_nonexistent_workspace_run_leaves_no_artifacts(self, tmp_path, capsys):
        """A failed --workspace run must not mutate the tree: no parent
        directories, no sibling lock file."""
        workspace_path = os.path.join(str(tmp_path), "new", "sub", "ws")

        rc = cli_main.run(["run", "--workspace", workspace_path, "--json"])

        assert rc == 1
        records = json.loads(capsys.readouterr().out)["records"]
        assert any(r.get("error") == "invalid_workspace" for r in records)
        assert not os.path.exists(os.path.join(str(tmp_path), "new"))
