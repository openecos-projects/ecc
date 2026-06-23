import json
import os

from chipcompiler.cli import main as cli_main


class TestCheck:
    def test_check_passes_valid_config(self, tmp_path, monkeypatch, capsys, create_cli_project):
        project_dir = create_cli_project()
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root: None,
        )
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "checked" in out

    def test_check_from_inside_project_dir(self, tmp_path, monkeypatch, capsys, create_cli_project):
        project_dir = create_cli_project()
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root: None,
        )
        monkeypatch.chdir(project_dir)
        rc = cli_main.run(["check"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "checked" in out

    def test_check_fails_missing_ecc_toml(self, tmp_path):
        rc = cli_main.run(["check", "--project", str(tmp_path)])
        assert rc == 1

    def test_check_fails_malformed_toml(self, tmp_path, capsys):
        project_dir = tmp_path / "bad"
        project_dir.mkdir()
        (project_dir / "ecc.toml").write_text("[design\ninvalid {{{")
        rc = cli_main.run(["check", "--project", str(project_dir)])
        assert rc == 1

    def test_check_fails_missing_rtl(self, tmp_path, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path, "w") as f:
            f.write(
                '[design]\nname="gcd"\ntop="gcd"\nrtl=["rtl/missing.v"]\n'
                'clock_port="clk"\nfrequency_mhz=100\n'
                '[pdk]\nname="ics55"\nroot=""\n'
                '[flow]\npreset="rtl2gds"\nrun="default"\n',
            )
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 1

    def test_check_fails_empty_pdk_root(self, tmp_path, create_cli_project):
        project_dir = create_cli_project(pdk_root="")
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 1

    def test_check_fails_non_directory_pdk_root(self, tmp_path, create_cli_project):
        pdk_root = tmp_path / "ics55.txt"
        pdk_root.write_text("not a dir")
        project_dir = create_cli_project(pdk_root=str(pdk_root))
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 1

    def test_check_fails_unsupported_pdk(self, tmp_path, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content = content.replace('name = "ics55"', 'name = "unsupported"')
        with open(toml_path, "w") as f:
            f.write(content)
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 1

    def test_check_fails_unsupported_preset(self, tmp_path, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content = content.replace('preset = "rtl2gds"', 'preset = "unknown"')
        with open(toml_path, "w") as f:
            f.write(content)
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 1

    def test_check_fails_non_positive_frequency(self, tmp_path, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content = content.replace("frequency_mhz = 100.0", "frequency_mhz = -10")
        with open(toml_path, "w") as f:
            f.write(content)
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 1

    def test_check_fails_multiple_rtl(self, tmp_path, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content = content.replace(
            'rtl = ["rtl/gcd.v"]',
            'rtl = ["rtl/a.v", "rtl/b.v"]',
        )
        with open(toml_path, "w") as f:
            f.write(content)
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 1

    def test_check_fails_non_numeric_frequency(self, tmp_path, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content = content.replace("frequency_mhz = 100.0", 'frequency_mhz = "fast"')
        with open(toml_path, "w") as f:
            f.write(content)
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 1

    def test_check_json_output(self, tmp_path, monkeypatch, capsys, create_cli_project):
        project_dir = create_cli_project()
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root: None,
        )
        rc = cli_main.run(["check", "--project", project_dir, "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "records" in data
        assert data["records"][0]["status"] == "checked"
        assert data["records"][0]["project"] == "gcd"


class TestCheckFilelistValidation:
    def test_check_fails_filelist_with_missing_sources(self, tmp_path, monkeypatch):
        from chipcompiler.cli.project.config import _validate_pdk_contents

        monkeypatch.setattr(
            _validate_pdk_contents, "__wrapped__", lambda *a, **k: None, raising=False
        )
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents", lambda *a, **k: None
        )

        project_dir = tmp_path / "flproj"
        project_dir.mkdir()
        (project_dir / "rtl").mkdir()
        (project_dir / "rtl" / "gcd.v").write_text("module gcd; endmodule")

        filelist = project_dir / "rtl" / "files.f"
        filelist.write_text("gcd.v\nmissing.v\nother_missing.v\n")

        pdk_root = tmp_path / "ics55"
        pdk_root.mkdir()

        toml = f'''[design]
name = "gcd"
top = "gcd"
rtl = ["rtl/files.f"]
clock_port = "clk"
frequency_mhz = 100.0

[pdk]
name = "ics55"
root = "{pdk_root}"

[flow]
preset = "rtl2gds"
run = "default"
'''
        (project_dir / "ecc.toml").write_text(toml)
        rc = cli_main.run(["check", "--project", str(project_dir)])
        assert rc == 1

    def test_check_fails_invalid_filelist_directive(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents", lambda *a, **k: None
        )

        project_dir = tmp_path / "flproj2"
        project_dir.mkdir()
        (project_dir / "rtl").mkdir()

        filelist = project_dir / "rtl" / "files.f"
        filelist.write_text("gcd.v\n-f other.f\n")

        pdk_root = tmp_path / "ics55"
        pdk_root.mkdir()

        toml = f'''[design]
name = "gcd"
top = "gcd"
rtl = ["rtl/files.f"]
clock_port = "clk"
frequency_mhz = 100.0

[pdk]
name = "ics55"
root = "{pdk_root}"

[flow]
preset = "rtl2gds"
run = "default"
'''
        (project_dir / "ecc.toml").write_text(toml)
        rc = cli_main.run(["check", "--project", str(project_dir)])
        assert rc == 1


class TestMissingConfigErrorRecord:
    def test_check_missing_config_has_kind_error_json(self, tmp_path, capsys):
        rc = cli_main.run(["check", "--project", str(tmp_path), "--json"])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        record = data["records"][0]
        assert record["kind"] == "error"
        assert record["error"] == "missing_config"

    def test_check_missing_config_has_kind_error_text(self, tmp_path, capsys):
        rc = cli_main.run(["check", "--project", str(tmp_path)])
        assert rc == 1
        out = capsys.readouterr().out
        assert "[error]" in out
        assert "missing_config" in out

    def test_check_missing_config_has_disclosure_command(self, tmp_path, capsys):
        rc = cli_main.run(["check", "--project", str(tmp_path), "--json"])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        record = data["records"][0]
        assert "inspect" in record or "inspect_cmd" in record
