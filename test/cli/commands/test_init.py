
from chipcompiler.cli import main as cli_main


class TestInit:
    def test_init_creates_skeleton(self, tmp_path):
        project_path = str(tmp_path / "gcd")
        rc = cli_main.run(["init", project_path])
        assert rc == 0

        assert (tmp_path / "gcd" / "ecc.toml").exists()
        assert (tmp_path / "gcd" / "rtl").is_dir()
        assert (tmp_path / "gcd" / "constraints").is_dir()
        assert (tmp_path / "gcd" / "runs").is_dir()

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
