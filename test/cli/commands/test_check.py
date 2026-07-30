import json
import os

import pytest

from chipcompiler.cli import main as cli_main


class TestCheck:
    def test_check_passes_valid_config(self, tmp_path, monkeypatch, capsys, create_cli_project):
        project_dir = create_cli_project()
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "checked" in out

    def test_check_from_inside_project_dir(self, tmp_path, monkeypatch, capsys, create_cli_project):
        project_dir = create_cli_project()
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )
        monkeypatch.chdir(project_dir)
        rc = cli_main.run(["check"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "checked" in out

    def test_check_parses_config_once(self, tmp_path, monkeypatch, capsys, create_cli_project):
        project_dir = create_cli_project()
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )
        from chipcompiler.cli.project import config as config_module

        real_load = config_module.load_project_config
        calls = []

        def counting_load(config_path):
            calls.append(config_path)
            return real_load(config_path)

        monkeypatch.setattr("chipcompiler.cli.project.config.load_project_config", counting_load)

        rc = cli_main.run(["check", "--project", project_dir, "--json"])

        assert rc == 0
        assert len(calls) == 1

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
            lambda name, root, overrides=None: None,
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

    def test_check_pdk_overrides_valid(
        self, tmp_path, create_cli_project, minimal_ics55_pdk_factory
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=str(pdk_root))
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path, "a") as f:
            f.write('\n[pdk.overrides]\ndont_use = ["ICG*"]\n')
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 0

    def test_check_pdk_overrides_unknown_key(
        self, tmp_path, monkeypatch, create_cli_project, capsys
    ):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path, "a") as f:
            f.write('\n[pdk.overrides]\ndontuse = ["ICG*"]\n')
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._pdk_root_from_env",
            lambda: str(tmp_path / "ics55"),
        )
        (tmp_path / "ics55").mkdir(exist_ok=True)
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "unknown PDK override fields" in out
        assert "dontuse" in out

    def test_check_pdk_overrides_type_mismatch(
        self, tmp_path, monkeypatch, create_cli_project, capsys
    ):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path, "a") as f:
            f.write('\n[pdk.overrides]\nabc_load = "fast"\n')
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._pdk_root_from_env",
            lambda: str(tmp_path / "ics55"),
        )
        (tmp_path / "ics55").mkdir(exist_ok=True)
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "must be a number" in out

    def test_check_pdk_overrides_nonexistent_tech(
        self, tmp_path, create_cli_project, minimal_ics55_pdk_factory, capsys
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=str(pdk_root))
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path, "a") as f:
            f.write('\n[pdk.overrides]\ntech = "/no/such.lef"\n')
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "PDK tech LEF not found" in out
        assert "/no/such.lef" in out

    @pytest.mark.parametrize(
        ("field", "message"),
        [
            ("mapping_file", "PDK mapping file not found"),
            ("sdc", "PDK SDC file not found"),
            ("spef", "PDK SPEF file not found"),
        ],
    )
    def test_check_pdk_overrides_nonexistent_optional_path(
        self, tmp_path, create_cli_project, minimal_ics55_pdk_factory, capsys, field, message
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=str(pdk_root))
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path, "a") as f:
            f.write(f'\n[pdk.overrides]\n{field} = "/no/such.file"\n')
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert message in out
        assert "/no/such.file" in out

    def test_check_pdk_overrides_relative_sdc_resolves_against_project_dir(
        self, tmp_path, monkeypatch, create_cli_project, minimal_ics55_pdk_factory
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=str(pdk_root))
        sdc_path = os.path.join(project_dir, "constraints", "design.sdc")
        with open(sdc_path, "w") as f:
            f.write("create_clock -period 1 [get_ports clk]\n")
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path, "a") as f:
            f.write('\n[pdk.overrides]\nsdc = "constraints/design.sdc"\n')
        monkeypatch.chdir(tmp_path)

        rc = cli_main.run(["check", "--project", project_dir])

        assert rc == 0

    def test_check_pdk_overrides_missing_relative_sdc_reports_project_resolved_path(
        self, tmp_path, monkeypatch, create_cli_project, minimal_ics55_pdk_factory, capsys
    ):
        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        project_dir = create_cli_project(pdk_root=str(pdk_root))
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path, "a") as f:
            f.write('\n[pdk.overrides]\nsdc = "constraints/missing.sdc"\n')
        monkeypatch.chdir(tmp_path)

        rc = cli_main.run(["check", "--project", project_dir])

        assert rc == 1
        out = capsys.readouterr().out
        assert "PDK SDC file not found" in out
        assert os.path.join(project_dir, "constraints", "missing.sdc") in out

    @pytest.mark.parametrize("field", ["lefs", "dont_use"])
    def test_check_pdk_overrides_non_string_list_element(
        self, tmp_path, create_cli_project, capsys, field
    ):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path, "a") as f:
            f.write(f"\n[pdk.overrides]\n{field} = [1]\n")

        rc = cli_main.run(["check", "--project", project_dir])

        captured = capsys.readouterr()
        assert rc == 1
        assert f"PDK override '{field}' elements must be strings" in captured.out
        assert "Traceback" not in captured.err

    def test_check_pdk_overrides_non_table(self, tmp_path, create_cli_project, capsys):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content = content.replace("[pdk]", '[pdk]\noverrides = "not a table"')
        with open(toml_path, "w") as f:
            f.write(content)
        rc = cli_main.run(["check", "--project", project_dir])
        assert rc == 1
        out = capsys.readouterr().out
        assert "must be a table" in out


class TestCheckFlowRunShape:
    @pytest.mark.parametrize(
        "run_line",
        ['run = "exp1"', 'run = "sweeps/s1/r4"', 'run = "/data/runs/x"'],
    )
    def test_check_accepts_run_shapes(
        self, tmp_path, monkeypatch, create_cli_project, set_flow_run, run_line
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, run_line)
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(["check", "--project", project_dir])

        assert rc == 0

    @pytest.mark.parametrize(
        ("run_line", "reason"),
        [
            ('run = ""', "unsupported flow.run: "),
            ('run = "   "', "unsupported flow.run:    "),
            ('run = " exp1 "', "unsupported flow.run:  exp1 "),
            ("run = 42", "unsupported flow.run: 42"),
            ('run = "\\u0000"', "unsupported flow.run: \x00"),
        ],
    )
    def test_check_rejects_invalid_run_shapes(
        self, tmp_path, capsys, create_cli_project, set_flow_run, run_line, reason
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, run_line)

        rc = cli_main.run(["check", "--project", project_dir, "--json"])

        assert rc == 1
        records = json.loads(capsys.readouterr().out)["records"]
        assert any(record.get("reason") == reason for record in records)


class TestCheckRunDirDisplay:
    def test_check_reports_default_run_dir(self, tmp_path, monkeypatch, capsys, create_cli_project):
        project_dir = create_cli_project()
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(["check", "--project", project_dir, "--json"])

        assert rc == 0
        records = json.loads(capsys.readouterr().out)["records"]
        assert records[0] == {
            "project": "gcd",
            "status": "checked",
            "config": "ecc.toml",
            "run_dir": "runs/default",
            "run": f"ecc run --project {project_dir}",
            "inspect_cmd": f"ecc status --project {project_dir}",
        }

    def test_check_reports_configured_run_dir(
        self, tmp_path, monkeypatch, capsys, create_cli_project, set_flow_run
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = "exp1"')
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(["check", "--project", project_dir, "--json"])

        assert rc == 0
        records = json.loads(capsys.readouterr().out)["records"]
        assert records[0] == {
            "project": "gcd",
            "status": "checked",
            "config": "ecc.toml",
            "run_dir": os.path.join("runs", "exp1"),
            "run": f"ecc run --project {project_dir}",
            "inspect_cmd": f"ecc status --project {project_dir}",
        }

    def test_check_reports_absolute_configured_run_dir(
        self, tmp_path, monkeypatch, capsys, create_cli_project, set_flow_run
    ):
        project_dir = create_cli_project()
        abs_run = str(tmp_path / "external_run")
        set_flow_run(project_dir, f'run = "{abs_run}"')
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(["check", "--project", project_dir, "--json"])

        assert rc == 0
        records = json.loads(capsys.readouterr().out)["records"]
        assert records[0] == {
            "project": "gcd",
            "status": "checked",
            "config": "ecc.toml",
            "run_dir": abs_run,
            "run": f"ecc run --project {project_dir}",
            "inspect_cmd": f"ecc status --project {project_dir}",
        }

    def test_check_reports_dotdot_prefixed_name_run_dir_relatively(
        self, tmp_path, monkeypatch, capsys, create_cli_project, set_flow_run
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = "..foo/run"')
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(["check", "--project", project_dir, "--json"])

        assert rc == 0
        records = json.loads(capsys.readouterr().out)["records"]
        assert records[0] == {
            "project": "gcd",
            "status": "checked",
            "config": "ecc.toml",
            "run_dir": os.path.join("..foo", "run"),
            "run": f"ecc run --project {project_dir}",
            "inspect_cmd": f"ecc status --project {project_dir}",
        }

    def test_check_reports_parent_escaping_run_dir_absolute(
        self, tmp_path, monkeypatch, capsys, create_cli_project, set_flow_run
    ):
        project_dir = create_cli_project()
        set_flow_run(project_dir, 'run = "../outside"')
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(["check", "--project", project_dir, "--json"])

        assert rc == 0
        records = json.loads(capsys.readouterr().out)["records"]
        assert records[0] == {
            "project": "gcd",
            "status": "checked",
            "config": "ecc.toml",
            "run_dir": os.path.join(project_dir, "..", "outside"),
            "run": f"ecc run --project {project_dir}",
            "inspect_cmd": f"ecc status --project {project_dir}",
        }

    def test_check_reports_symlink_escaping_run_dir_absolute(
        self, tmp_path, monkeypatch, capsys, create_cli_project, set_flow_run
    ):
        project_dir = create_cli_project()
        external = tmp_path / "external"
        external.mkdir()
        os.symlink(str(external), os.path.join(project_dir, "link"))
        set_flow_run(project_dir, 'run = "link/run"')
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(["check", "--project", project_dir, "--json"])

        assert rc == 0
        records = json.loads(capsys.readouterr().out)["records"]
        assert records[0] == {
            "project": "gcd",
            "status": "checked",
            "config": "ecc.toml",
            "run_dir": os.path.join(project_dir, "link", "run"),
            "run": f"ecc run --project {project_dir}",
            "inspect_cmd": f"ecc status --project {project_dir}",
        }

    def test_check_reports_absolute_in_project_run_dir_via_symlinked_project(
        self, tmp_path, monkeypatch, capsys, create_cli_project, set_flow_run
    ):
        project_dir = create_cli_project()
        project_link = str(tmp_path / "project_link")
        os.symlink(project_dir, project_link)
        set_flow_run(project_dir, f'run = "{os.path.join(project_dir, "runs", "exp1")}"')
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(["check", "--project", project_link, "--json"])

        assert rc == 0
        records = json.loads(capsys.readouterr().out)["records"]
        assert records[0] == {
            "project": "gcd",
            "status": "checked",
            "config": "ecc.toml",
            "run_dir": os.path.join("runs", "exp1"),
            "run": f"ecc run --project {project_link}",
            "inspect_cmd": f"ecc status --project {project_link}",
        }
