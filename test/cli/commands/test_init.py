import errno
import json
import tomllib

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.project import project_init
from chipcompiler.cli.project.timing_template import SDC_INPUT_TEMPLATE


class TestInit:
    def test_init_falls_back_when_filesystem_rejects_renameat2_flags(self, tmp_path, monkeypatch):
        def unsupported_renameat2(source, target, flags):
            raise OSError(errno.EINVAL, "Invalid argument", target)

        monkeypatch.setattr(project_init, "_renameat2", unsupported_renameat2)
        selected = tmp_path / "selected"
        selected.mkdir(mode=0o750)

        assert cli_main.run(["init", str(selected), "--design-name", "gcd"]) == 0
        assert (selected / "project.json").is_file()
        assert (selected / "ecc.toml").is_file()
        assert selected.stat().st_mode & 0o777 == 0o750

    def test_init_creates_skeleton(self, tmp_path):
        project_path = str(tmp_path / "gcd")
        rc = cli_main.run(["init", project_path])
        assert rc == 0

        assert (tmp_path / "gcd" / "ecc.toml").exists()
        assert (tmp_path / "gcd" / "rtl").is_dir()
        assert {entry.name for entry in (tmp_path / "gcd").iterdir()} == {
            "ecc.toml",
            "project.json",
            "rtl",
            "sdc",
        }
        timing = tmp_path / "gcd" / "sdc" / "gcd.tcl"
        assert timing.read_text() == SDC_INPUT_TEMPLATE
        config = tomllib.loads((tmp_path / "gcd" / "ecc.toml").read_text())
        assert config["design"]["sdc"] == "sdc/gcd.tcl"
        manifest = json.loads((tmp_path / "gcd" / "project.json").read_text())
        assert manifest["schema_version"] == 1
        assert manifest["workspaces"] == []
        assert manifest["root_path"] == str(tmp_path / "gcd")
        assert manifest["base_design"]["sdc"] == config["design"]["sdc"]
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

    @pytest.mark.parametrize("absolute", [False, True])
    def test_init_keeps_timing_template_inside_project(self, tmp_path, absolute):
        project = tmp_path / "project"
        name = str(tmp_path / "outside") if absolute else "../outside"
        assert cli_main.run(["init", str(project), "--design-name", name]) == 1
        assert list(tmp_path.iterdir()) == []

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
