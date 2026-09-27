import json

from chipcompiler.cli import main as cli_main


class TestInit:
    def test_init_creates_skeleton(self, tmp_path):
        project_path = str(tmp_path / "gcd")
        rc = cli_main.run(["init", project_path])
        assert rc == 0

        assert (tmp_path / "gcd" / "ecc.toml").exists()
        assert (tmp_path / "gcd" / "rtl").is_dir()
        assert (tmp_path / "gcd" / "constraints").is_dir()
        manifest = json.loads((tmp_path / "gcd" / "project.json").read_text())
        assert manifest["schema_version"] == 1
        assert manifest["workspaces"] == []
        assert manifest["root_path"] == str(tmp_path / "gcd")
        assert not (tmp_path / "gcd" / "runs").exists()

    def test_init_output_has_disclosure_commands(self, tmp_path, capsys):
        project_path = str(tmp_path / "myproj")
        rc = cli_main.run(["init", project_path])
        assert rc == 0
        out = capsys.readouterr().out
        assert "ecc check" in out
        assert "ecc run" in out

    def test_init_fails_if_ecc_toml_exists(self, tmp_path):
        project_dir = tmp_path / "gcd"
        project_dir.mkdir()
        (project_dir / "ecc.toml").write_text("[design]\n")
        rc = cli_main.run(["init", str(project_dir)])
        assert rc == 1

    def test_init_rejects_empty_name(self):
        rc = cli_main.run(["init", ""])
        assert rc == 1

    def test_init_uses_basename_for_design_name(self, tmp_path):
        project_path = str(tmp_path / "subdir" / "mydesign")
        rc = cli_main.run(["init", project_path])
        assert rc == 0
        toml = (tmp_path / "subdir" / "mydesign" / "ecc.toml").read_text()
        assert 'name = "mydesign"' in toml
        assert "rtl/mydesign.v" in toml

    def test_init_replaces_selected_empty_directory_atomically(self, tmp_path):
        project = tmp_path / "selected"
        project.mkdir(mode=0o750)

        assert cli_main.run(["init", str(project)]) == 0

        assert (project / "ecc.toml").is_file()
        assert (project / "project.json").is_file()
        assert project.stat().st_mode & 0o777 == 0o750

    def test_init_rejects_nonempty_directory_without_partial_writes(self, tmp_path):
        project = tmp_path / "occupied"
        project.mkdir()
        (project / "keep.txt").write_text("keep")

        assert cli_main.run(["init", str(project)]) == 1

        assert (project / "keep.txt").read_text() == "keep"
        assert not (project / "ecc.toml").exists()
        assert not (project / "project.json").exists()

    def test_init_builds_valid_mpc_snapshot(self, tmp_path):
        mpc = tmp_path / "mpc"
        (mpc / "spec").mkdir(parents=True)
        (mpc / "spec" / "spec.json.in").write_text(
            json.dumps(
                {
                    "resource_id": "mpc:frame",
                    "version": "1.0.0",
                    "number": 1,
                    "designs": [{"design_name": "frame", "core_template": {"minimum_area": 100}}],
                }
            )
        )
        project = tmp_path / "project"

        rc = cli_main.run(
            [
                "init",
                str(project),
                "--mpc-resource-id",
                "mpc:frame",
                "--mpc-display-name",
                "Frame",
                "--mpc-version",
                "1.0.0",
                "--mpc-root",
                str(mpc),
                "--mpc-design-index",
                "0",
            ]
        )

        assert rc == 0
        manifest = json.loads((project / "project.json").read_text())
        assert manifest["mpc"]["design"] == {"index": 0, "design_name": "frame"}
        assert manifest["mpc"]["core_template"] == {"minimum_area": 100}
