import json
import os

from chipcompiler.cli import main as cli_main


class TestTomlValidationErrors:
    def _create_project_with_invalid_param(self, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += '\n[params.cts]\nmax_fanout = "not_an_int"\n'
        with open(toml_path, "w") as f:
            f.write(content)
        return project_dir

    def test_check_fails_invalid_param_type(self, tmp_path, capsys, create_cli_project):
        project_dir = self._create_project_with_invalid_param(create_cli_project)
        rc = cli_main.run(["check", "--project", project_dir, "--json"])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        reasons = [r.get("reason", "") for r in data["records"]]
        assert any("params" in r for r in reasons)

    def test_check_fails_unknown_param_key(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += "\n[params.bogus]\nkey = 5\n"
        with open(toml_path, "w") as f:
            f.write(content)
        rc = cli_main.run(["check", "--project", project_dir, "--json"])
        assert rc == 1

    def test_run_fails_invalid_param_type(self, tmp_path, create_cli_project):
        project_dir = self._create_project_with_invalid_param(create_cli_project)
        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 1


class TestNativeTomlTypeValidation:
    def test_check_rejects_float_for_int(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += "\n[params.cts]\nmax_fanout = 16.5\n"
        with open(toml_path, "w") as f:
            f.write(content)
        rc = cli_main.run(["check", "--project", project_dir, "--json"])
        assert rc == 1

    def test_check_rejects_bool_for_int(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += "\n[params.cts]\nmax_fanout = true\n"
        with open(toml_path, "w") as f:
            f.write(content)
        rc = cli_main.run(["check", "--project", project_dir, "--json"])
        assert rc == 1

    def test_check_rejects_float_in_list_int(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += "\n[params.floorplan]\ncore_margin = [2.5, 3]\n"
        with open(toml_path, "w") as f:
            f.write(content)
        rc = cli_main.run(["check", "--project", project_dir, "--json"])
        assert rc == 1

    def test_check_accepts_valid_int(self, tmp_path, capsys, monkeypatch, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += "\n[params.cts]\nmax_fanout = 16\n"
        with open(toml_path, "w") as f:
            f.write(content)
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: [],
        )
        rc = cli_main.run(["check", "--project", project_dir, "--json"])
        assert rc == 0


class TestBoolParamValidation:
    def _append_flow_param(self, create_cli_project, value):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += f"\n[params.flow]\nrun_analysis = {value}\n"
        with open(toml_path, "w") as f:
            f.write(content)
        return project_dir

    def test_check_rejects_bad_bool_string(self, tmp_path, capsys, create_cli_project):
        project_dir = self._append_flow_param(create_cli_project, '"maybe"')
        rc = cli_main.run(["check", "--project", project_dir, "--json"])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        reasons = [r.get("reason", "") for r in data["records"]]
        assert any("params" in r for r in reasons)

    def test_bool_like_string_accepted_and_coerced(
        self, tmp_path, capsys, monkeypatch, create_cli_project
    ):
        project_dir = self._append_flow_param(create_cli_project, '"false"')
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: [],
        )
        rc = cli_main.run(["check", "--project", project_dir, "--json"])
        assert rc == 0
        capsys.readouterr()
        rc = cli_main.run(["config", "--resolved", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        records = [r for r in data["records"] if r.get("key") == "flow.run_analysis"]
        assert len(records) == 1
        assert records[0]["value"] is False
        assert records[0]["source"] == "ecc.toml"


class TestParamHandlersRejectInvalidToml:
    """Param list/show/diff must return errors when ecc.toml has invalid [params.*]."""

    def _write_invalid_toml(self, project_dir):
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += "\n[params.cts]\nmax_fanout = 16.5\n"
        with open(toml_path, "w") as f:
            f.write(content)

    def test_param_list_rejects_invalid_toml(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        self._write_invalid_toml(project_dir)
        rc = cli_main.run(["param", "list", "--project", project_dir, "--json"])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["error"] == "invalid_param_config"

    def test_param_show_rejects_invalid_toml(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        self._write_invalid_toml(project_dir)
        rc = cli_main.run(["param", "show", "cts.max_fanout", "--project", project_dir, "--json"])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["error"] == "invalid_param_config"

    def test_param_diff_rejects_invalid_toml(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        self._write_invalid_toml(project_dir)
        rc = cli_main.run(["param", "diff", "--project", project_dir, "--json"])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["error"] == "invalid_param_config"


class TestZeroFrequencyRejected:
    """ecc param set design.frequency_mhz 0 must be rejected."""

    def test_set_zero_rejected(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        rc = cli_main.run(["param", "set", "design.frequency_mhz", "0", "--project", project_dir])
        assert rc == 1

    def test_cli_set_zero_rejected(self, tmp_path, create_cli_project):
        project_dir = create_cli_project()
        rc = cli_main.run(
            [
                "run",
                "--project",
                project_dir,
                "--set",
                "design.frequency_mhz=0",
            ]
        )
        assert rc == 1


class TestMalformedTomlRejected:
    """ecc param list/show/diff must reject syntactically malformed ecc.toml."""

    def _write_malformed_toml(self, project_dir):
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path, "w") as f:
            f.write('[design\nname = "gcd"\n')

    def test_param_list_rejects_malformed(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        self._write_malformed_toml(project_dir)
        rc = cli_main.run(["param", "list", "--project", project_dir, "--json"])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["error"] == "invalid_param_config"

    def test_param_show_rejects_malformed(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        self._write_malformed_toml(project_dir)
        rc = cli_main.run(
            ["param", "show", "design.frequency_mhz", "--project", project_dir, "--json"]
        )
        assert rc == 1

    def test_param_diff_rejects_malformed(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        self._write_malformed_toml(project_dir)
        rc = cli_main.run(["param", "diff", "--project", project_dir, "--json"])
        assert rc == 1
