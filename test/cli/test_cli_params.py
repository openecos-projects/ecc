import json
import os

from chipcompiler.cli import main as cli_main


def _create_valid_project(tmp_path, name="gcd", pdk_root=None, freq=100.0):
    project_dir = tmp_path / name
    project_dir.mkdir(exist_ok=True)
    (project_dir / "rtl").mkdir(exist_ok=True)
    (project_dir / "constraints").mkdir(exist_ok=True)
    (project_dir / "runs").mkdir(exist_ok=True)

    rtl_file = project_dir / "rtl" / "gcd.v"
    rtl_file.write_text("module gcd(input clk); endmodule\n")

    if pdk_root is None:
        pdk_root = tmp_path / "ics55"
        pdk_root.mkdir(exist_ok=True)

    toml = f'''[design]
name = "{name}"
top = "{name}"
rtl = ["rtl/gcd.v"]
clock_port = "clk"
frequency_mhz = {freq}

[pdk]
name = "ics55"
root = "{pdk_root}"

[flow]
preset = "rtl2gds"
run = "default"
'''
    (project_dir / "ecc.toml").write_text(toml)
    return str(project_dir)


class TestParamList:
    def test_param_list_text_output(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "list", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "place.target_density" in out

    def test_param_list_json(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "list", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "records" in data
        params = [r["param"] for r in data["records"]]
        assert "place.target_density" in params

    def test_param_list_jsonl(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "list", "--project", project_dir, "--jsonl"])
        assert rc == 0
        lines = capsys.readouterr().out.strip().split("\n")
        objects = [json.loads(ln) for ln in lines]
        assert len(objects) == 12

    def test_param_list_plain(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "list", "--project", project_dir, "--plain"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "\033[" not in out
        assert "place.target_density" in out


class TestParamShow:
    def test_param_show_known_key(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "show", "place.target_density", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "place.target_density" in out

    def test_param_show_json(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "show", "place.target_density", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        record = data["records"][0]
        assert record["param"] == "place.target_density"
        assert record["default"] == 0.8
        assert "source" in record
        assert "maps_to" in record

    def test_param_show_unknown_key(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "show", "unknown.key", "--project", project_dir])
        assert rc == 1


class TestParamSet:
    def test_param_set_writes_toml(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "set", "place.target_density", "0.65", "--project", project_dir])
        assert rc == 0

        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        assert "target_density" in content
        assert "0.65" in content

    def test_param_set_then_show(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        cli_main.run(["param", "set", "place.target_density", "0.65", "--project", project_dir])
        capsys.readouterr()  # flush set output

        rc = cli_main.run(["param", "show", "place.target_density", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        record = data["records"][0]
        assert record["value"] == 0.65
        assert record["source"] == "ecc.toml"

    def test_param_set_rejects_unknown_key(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "set", "bogus.key", "5", "--project", project_dir])
        assert rc == 1

    def test_param_set_rejects_invalid_value(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "set", "place.target_density", "1.5", "--project", project_dir])
        assert rc == 1

    def test_param_set_preserves_other_sections(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        cli_main.run(["param", "set", "synth.max_fanout", "16", "--project", project_dir])

        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        assert "[design]" in content
        assert "[pdk]" in content
        assert "[flow]" in content


class TestParamUnset:
    def test_param_unset_removes_override(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        cli_main.run(["param", "set", "place.target_density", "0.65", "--project", project_dir])
        capsys.readouterr()  # flush set output

        rc = cli_main.run(["param", "unset", "place.target_density", "--project", project_dir])
        assert rc == 0
        capsys.readouterr()  # flush unset output

        rc = cli_main.run(["param", "show", "place.target_density", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        record = data["records"][0]
        assert record["source"] == "default"

    def test_param_unset_noop_when_absent(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "unset", "place.target_density", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "no override" in out


class TestParamDiff:
    def test_param_diff_shows_overrides(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        cli_main.run(["param", "set", "place.target_density", "0.65", "--project", project_dir])
        capsys.readouterr()  # flush set output

        rc = cli_main.run(["param", "diff", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        records = data["records"]
        assert len(records) == 1
        assert records[0]["param"] == "place.target_density"

    def test_param_diff_clean_when_no_overrides(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "diff", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0].get("diff_status") == "clean"


class TestRunSet:
    def test_run_set_override(self, tmp_path, monkeypatch, capsys):
        from types import SimpleNamespace

        project_dir = _create_valid_project(tmp_path)
        workspace_obj = SimpleNamespace(name="workspace")
        capture = {"kwargs": None}

        def fake_create(**kwargs):
            capture["kwargs"] = kwargs
            return workspace_obj

        monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create)
        monkeypatch.setattr("chipcompiler.engine.EngineFlow", type(
            "DummyFlow", (), {
                "__init__": lambda self, workspace: None,
                "has_init": lambda self: False,
                "add_step": lambda self, **kw: None,
                "create_step_workspaces": lambda self: None,
                "run_steps": lambda self: True,
            },
        ))
        monkeypatch.setattr(
            "chipcompiler.rtl2gds.build_rtl2gds_flow",
            lambda: [("Synthesis", "yosys", "Unstart")],
        )
        monkeypatch.setattr(
            "chipcompiler.cli.config._validate_pdk_contents",
            lambda name, root: None,
        )
        monkeypatch.setattr(
            "chipcompiler.cli.progress.should_enable_run_progress",
            lambda *a, **kw: False,
        )

        rc = cli_main.run([
            "run", "--project", project_dir,
            "--set", "place.target_density=0.65",
        ])
        assert rc == 0

        params = capture["kwargs"]["parameters"]
        assert params.get("DreamPlace", {}).get("target_density") == 0.65

    def test_run_set_rejects_unknown_key(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run([
            "run", "--project", project_dir,
            "--set", "bogus.key=5",
        ])
        assert rc == 1

    def test_run_set_rejects_invalid_value(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run([
            "run", "--project", project_dir,
            "--set", "place.target_density=1.5",
        ])
        assert rc == 1

    def test_run_set_does_not_modify_toml(self, tmp_path, monkeypatch, capsys):
        from types import SimpleNamespace

        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            original_toml = f.read()

        workspace_obj = SimpleNamespace(name="workspace")

        def fake_create(**kwargs):
            return workspace_obj

        monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create)
        monkeypatch.setattr("chipcompiler.engine.EngineFlow", type(
            "DummyFlow", (), {
                "__init__": lambda self, workspace: None,
                "has_init": lambda self: False,
                "add_step": lambda self, **kw: None,
                "create_step_workspaces": lambda self: None,
                "run_steps": lambda self: True,
            },
        ))
        monkeypatch.setattr(
            "chipcompiler.rtl2gds.build_rtl2gds_flow",
            lambda: [("Synthesis", "yosys", "Unstart")],
        )
        monkeypatch.setattr(
            "chipcompiler.cli.config._validate_pdk_contents",
            lambda name, root: None,
        )
        monkeypatch.setattr(
            "chipcompiler.cli.progress.should_enable_run_progress",
            lambda *a, **kw: False,
        )

        cli_main.run([
            "run", "--project", project_dir,
            "--set", "place.target_density=0.65",
        ])

        with open(toml_path) as f:
            current_toml = f.read()
        assert current_toml == original_toml


class TestOutputContracts:
    def test_plain_no_ansi(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "list", "--project", project_dir, "--plain"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "\033[" not in out

    def test_json_no_ansi(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "list", "--project", project_dir, "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "\033[" not in out

    def test_jsonl_no_ansi(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "list", "--project", project_dir, "--jsonl"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "\033[" not in out

    def test_json_uses_records_envelope(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "list", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "records" in data
        assert isinstance(data["records"], list)

    def test_plain_is_line_oriented(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "list", "--project", project_dir, "--plain"])
        assert rc == 0
        out = capsys.readouterr().out
        lines = [l for l in out.strip().split("\n") if l.strip()]
        assert len(lines) == 12


class TestConfigResolved:
    def test_config_resolved_includes_param_records(self, tmp_path, monkeypatch, capsys):
        project_dir = _create_valid_project(tmp_path)
        monkeypatch.setattr(
            "chipcompiler.cli.config._validate_pdk_contents",
            lambda name, root: None,
        )
        run_dir = os.path.join(project_dir, "runs", "default")
        home = os.path.join(run_dir, "home")
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(home, "flow.json"), "w") as f:
            json.dump({"steps": []}, f)

        rc = cli_main.run(["config", "--resolved", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        records = data["records"]
        param_records = [r for r in records if r.get("kind") == "param"]
        assert len(param_records) == 12
        first_param = param_records[0]
        assert "source" in first_param
        assert "maps_to" in first_param

    def test_config_resolved_shows_toml_source(self, tmp_path, monkeypatch, capsys):
        project_dir = _create_valid_project(tmp_path)
        monkeypatch.setattr(
            "chipcompiler.cli.config._validate_pdk_contents",
            lambda name, root: None,
        )
        cli_main.run(["param", "set", "place.target_density", "0.65", "--project", project_dir])
        capsys.readouterr()  # flush set output

        run_dir = os.path.join(project_dir, "runs", "default")
        home = os.path.join(run_dir, "home")
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(home, "flow.json"), "w") as f:
            json.dump({"steps": []}, f)

        rc = cli_main.run(["config", "--resolved", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        param_records = [r for r in data["records"] if r.get("kind") == "param"]
        density = next(r for r in param_records if r["key"] == "place.target_density")
        assert density["value"] == 0.65
        assert density["source"] == "ecc.toml"


class TestTomlValidationErrors:
    def _create_project_with_invalid_param(self, tmp_path):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += '\n[params.synth]\nmax_fanout = "not_an_int"\n'
        with open(toml_path, "w") as f:
            f.write(content)
        return project_dir

    def test_check_fails_invalid_param_type(self, tmp_path, capsys):
        project_dir = self._create_project_with_invalid_param(tmp_path)
        rc = cli_main.run(["check", "--project", project_dir, "--json"])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        reasons = [r.get("reason", "") for r in data["records"]]
        assert any("params" in r for r in reasons)

    def test_check_fails_unknown_param_key(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += '\n[params.bogus]\nkey = 5\n'
        with open(toml_path, "w") as f:
            f.write(content)
        rc = cli_main.run(["check", "--project", project_dir, "--json"])
        assert rc == 1

    def test_run_fails_invalid_param_type(self, tmp_path):
        project_dir = self._create_project_with_invalid_param(tmp_path)
        rc = cli_main.run(["run", "--project", project_dir])
        assert rc == 1


class TestPrettyOutput:
    def test_param_list_default_is_grouped_text(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "list", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "place" in out
        assert "place.target_density" in out

    def test_param_list_plain_is_one_line_per_record(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "list", "--project", project_dir, "--plain"])
        assert rc == 0
        out = capsys.readouterr().out
        lines = [l for l in out.strip().split("\n") if l.strip()]
        assert len(lines) == 12
        assert "\033[" not in out

    def test_param_show_default_is_pretty(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "show", "place.target_density", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "place.target_density" in out
        assert "source" in out
        assert "default" in out

    def test_param_set_default_is_pretty(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "set", "place.target_density", "0.65", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "0.65" in out

    def test_param_diff_default_is_pretty(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        cli_main.run(["param", "set", "place.target_density", "0.65", "--project", project_dir])
        capsys.readouterr()
        rc = cli_main.run(["param", "diff", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "place.target_density" in out


class TestResolvedListValues:
    def test_param_list_json_has_value_and_source(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        cli_main.run(["param", "set", "place.target_density", "0.65", "--project", project_dir])
        capsys.readouterr()

        rc = cli_main.run(["param", "list", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        records = data["records"]
        density = next(r for r in records if r["param"] == "place.target_density")
        assert density["value"] == 0.65
        assert density["source"] == "ecc.toml"
        assert "default" in density
        assert "maps_to" in density
        assert "inspect" in density

    def test_param_list_default_source_when_no_overrides(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "list", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        for r in data["records"]:
            if r["param"] == "design.frequency_mhz":
                assert r["source"] == "ecc.toml"
            else:
                assert r["source"] == "default"


class TestDiffFiltering:
    def test_diff_only_shows_values_that_differ(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        cli_main.run(["param", "set", "place.target_density", "0.65", "--project", project_dir])
        capsys.readouterr()

        rc = cli_main.run(["param", "diff", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        records = data["records"]
        assert len(records) == 1
        assert records[0]["param"] == "place.target_density"
        assert records[0]["value"] == 0.65
        assert records[0]["default"] != 0.65

    def test_diff_clean_when_set_to_default(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        schema_default = 0.8
        cli_main.run(["param", "set", "place.target_density", str(schema_default), "--project", project_dir])
        capsys.readouterr()

        rc = cli_main.run(["param", "diff", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0].get("diff_status") == "clean"


class TestScopedTomlEdit:
    def test_set_preserves_unrelated_sections(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            original = f.read()

        cli_main.run(["param", "set", "synth.max_fanout", "16", "--project", project_dir])
        capsys.readouterr()

        with open(toml_path) as f:
            after = f.read()
        design_section = original[original.index("[design]"):original.index("[pdk]")]
        assert design_section in after

    def test_set_preserves_comments(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content = content.replace("[design]", "[design]\n# my design")
        with open(toml_path, "w") as f:
            f.write(content)

        cli_main.run(["param", "set", "synth.max_fanout", "16", "--project", project_dir])
        capsys.readouterr()

        with open(toml_path) as f:
            after = f.read()
        assert "# my design" in after

    def test_set_same_key_twice_has_one_assignment(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")

        cli_main.run(["param", "set", "place.target_density", "0.65", "--project", project_dir])
        capsys.readouterr()

        cli_main.run(["param", "set", "place.target_density", "0.7", "--project", project_dir])
        capsys.readouterr()

        with open(toml_path) as f:
            content = f.read()
        assert content.count("target_density") == 1
        assert "0.7" in content
        assert "0.65" not in content

    def test_set_then_show_still_works(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)

        cli_main.run(["param", "set", "place.target_density", "0.65", "--project", project_dir])
        capsys.readouterr()

        cli_main.run(["param", "set", "place.target_density", "0.7", "--project", project_dir])
        capsys.readouterr()

        rc = cli_main.run(["param", "show", "place.target_density", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["value"] == 0.7


class TestNativeTomlTypeValidation:
    def test_check_rejects_float_for_int(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += '\n[params.synth]\nmax_fanout = 16.5\n'
        with open(toml_path, "w") as f:
            f.write(content)
        rc = cli_main.run(["check", "--project", project_dir, "--json"])
        assert rc == 1

    def test_check_rejects_bool_for_int(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += '\n[params.synth]\nmax_fanout = true\n'
        with open(toml_path, "w") as f:
            f.write(content)
        rc = cli_main.run(["check", "--project", project_dir, "--json"])
        assert rc == 1

    def test_check_rejects_float_in_list_int(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += '\n[params.floorplan]\ncore_margin = [2.5, 3]\n'
        with open(toml_path, "w") as f:
            f.write(content)
        rc = cli_main.run(["check", "--project", project_dir, "--json"])
        assert rc == 1

    def test_check_accepts_valid_int(self, tmp_path, capsys, monkeypatch):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += '\n[params.synth]\nmax_fanout = 16\n'
        with open(toml_path, "w") as f:
            f.write(content)
        monkeypatch.setattr(
            "chipcompiler.cli.config._validate_pdk_contents",
            lambda pdk_root, pdk_name: [],
        )
        rc = cli_main.run(["check", "--project", project_dir, "--json"])
        assert rc == 0


class TestCliProvenance:
    def test_run_set_reports_cli_source_in_config(self, tmp_path, monkeypatch, capsys):
        from types import SimpleNamespace

        project_dir = _create_valid_project(tmp_path)
        workspace_obj = SimpleNamespace(name="workspace")

        def fake_create(**kwargs):
            run_dir = kwargs["directory"]
            os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
            return workspace_obj

        monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create)
        monkeypatch.setattr("chipcompiler.engine.EngineFlow", type(
            "DummyFlow", (), {
                "__init__": lambda self, workspace: None,
                "has_init": lambda self: False,
                "add_step": lambda self, **kw: None,
                "create_step_workspaces": lambda self: None,
                "run_steps": lambda self: True,
            },
        ))
        monkeypatch.setattr(
            "chipcompiler.rtl2gds.build_rtl2gds_flow",
            lambda: [("Synthesis", "yosys", "Unstart")],
        )
        monkeypatch.setattr(
            "chipcompiler.cli.config._validate_pdk_contents",
            lambda name, root: None,
        )
        monkeypatch.setattr(
            "chipcompiler.cli.progress.should_enable_run_progress",
            lambda *a, **kw: False,
        )

        rc = cli_main.run([
            "run", "--project", project_dir,
            "--set", "synth.max_fanout=16",
        ])
        assert rc == 0
        capsys.readouterr()

        # Verify provenance file was written
        provenance = os.path.join(
            project_dir, "runs", "default", "home", "cli-param-overrides.json"
        )
        assert os.path.isfile(provenance)
        with open(provenance) as f:
            data = json.load(f)
        assert data["synth.max_fanout"] == 16

    def test_config_resolved_shows_cli_source(self, tmp_path, monkeypatch, capsys):
        from types import SimpleNamespace

        project_dir = _create_valid_project(tmp_path)
        workspace_obj = SimpleNamespace(name="workspace")

        def fake_create(**kwargs):
            run_dir = kwargs["directory"]
            os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
            return workspace_obj

        monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create)
        monkeypatch.setattr("chipcompiler.engine.EngineFlow", type(
            "DummyFlow", (), {
                "__init__": lambda self, workspace: None,
                "has_init": lambda self: False,
                "add_step": lambda self, **kw: None,
                "create_step_workspaces": lambda self: None,
                "run_steps": lambda self: True,
            },
        ))
        monkeypatch.setattr(
            "chipcompiler.rtl2gds.build_rtl2gds_flow",
            lambda: [("Synthesis", "yosys", "Unstart")],
        )
        monkeypatch.setattr(
            "chipcompiler.cli.config._validate_pdk_contents",
            lambda name, root: None,
        )
        monkeypatch.setattr(
            "chipcompiler.cli.progress.should_enable_run_progress",
            lambda *a, **kw: False,
        )

        # Run with --set
        rc = cli_main.run([
            "run", "--project", project_dir,
            "--set", "synth.max_fanout=16",
        ])
        assert rc == 0
        capsys.readouterr()

        # Now inspect config --resolved
        rc = cli_main.run(["config", "--resolved", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        param_records = [r for r in data["records"] if r.get("kind") == "param"]
        fanout = next(r for r in param_records if r["key"] == "synth.max_fanout")
        assert fanout["value"] == 16
        assert fanout["source"] == "cli"

    def test_config_resolved_toml_plus_cli_precedence(self, tmp_path, monkeypatch, capsys):
        from types import SimpleNamespace

        project_dir = _create_valid_project(tmp_path)
        workspace_obj = SimpleNamespace(name="workspace")

        # Set a TOML override first
        cli_main.run(["param", "set", "synth.max_fanout", "16", "--project", project_dir])
        capsys.readouterr()

        def fake_create(**kwargs):
            run_dir = kwargs["directory"]
            os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
            return workspace_obj

        monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create)
        monkeypatch.setattr("chipcompiler.engine.EngineFlow", type(
            "DummyFlow", (), {
                "__init__": lambda self, workspace: None,
                "has_init": lambda self: False,
                "add_step": lambda self, **kw: None,
                "create_step_workspaces": lambda self: None,
                "run_steps": lambda self: True,
            },
        ))
        monkeypatch.setattr(
            "chipcompiler.rtl2gds.build_rtl2gds_flow",
            lambda: [("Synthesis", "yosys", "Unstart")],
        )
        monkeypatch.setattr(
            "chipcompiler.cli.config._validate_pdk_contents",
            lambda name, root: None,
        )
        monkeypatch.setattr(
            "chipcompiler.cli.progress.should_enable_run_progress",
            lambda *a, **kw: False,
        )

        # Run with different CLI override
        rc = cli_main.run([
            "run", "--project", project_dir,
            "--set", "synth.max_fanout=32",
        ])
        assert rc == 0
        capsys.readouterr()

        rc = cli_main.run(["config", "--resolved", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        param_records = [r for r in data["records"] if r.get("kind") == "param"]
        fanout = next(r for r in param_records if r["key"] == "synth.max_fanout")
        assert fanout["value"] == 32
        assert fanout["source"] == "cli"


class TestParamHandlersRejectInvalidToml:
    """Param list/show/diff must return errors when ecc.toml has invalid [params.*]."""

    def _write_invalid_toml(self, project_dir):
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += '\n[params.synth]\nmax_fanout = 16.5\n'
        with open(toml_path, "w") as f:
            f.write(content)

    def test_param_list_rejects_invalid_toml(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        self._write_invalid_toml(project_dir)
        rc = cli_main.run(["param", "list", "--project", project_dir, "--json"])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["error"] == "invalid_param_config"

    def test_param_show_rejects_invalid_toml(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        self._write_invalid_toml(project_dir)
        rc = cli_main.run(["param", "show", "synth.max_fanout", "--project", project_dir, "--json"])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["error"] == "invalid_param_config"

    def test_param_diff_rejects_invalid_toml(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        self._write_invalid_toml(project_dir)
        rc = cli_main.run(["param", "diff", "--project", project_dir, "--json"])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["error"] == "invalid_param_config"


class TestIndentedTomlKeys:
    """Scoped TOML edit must handle indented assignment lines."""

    def test_set_replaces_indented_key(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += '\n[params.place]\n  target_density = 0.65\n'
        with open(toml_path, "w") as f:
            f.write(content)

        cli_main.run(["param", "set", "place.target_density", "0.7", "--project", project_dir])
        capsys.readouterr()

        with open(toml_path) as f:
            after = f.read()
        assert after.count("target_density") == 1
        assert "0.7" in after

    def test_set_then_show_indented(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += '\n[params.place]\n  target_density = 0.65\n'
        with open(toml_path, "w") as f:
            f.write(content)

        cli_main.run(["param", "set", "place.target_density", "0.7", "--project", project_dir])
        capsys.readouterr()

        rc = cli_main.run(["param", "show", "place.target_density", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["value"] == 0.7

    def test_unset_removes_indented_key(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += '\n[params.place]\n  target_density = 0.65\n'
        with open(toml_path, "w") as f:
            f.write(content)

        cli_main.run(["param", "unset", "place.target_density", "--project", project_dir])
        capsys.readouterr()

        with open(toml_path) as f:
            after = f.read()
        assert "target_density" not in after

    def test_set_indented_preserves_other_sections(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += '\n[params.place]\n  target_density = 0.65\n\n[flow]\npreset = "rtl2gds"\n'
        with open(toml_path, "w") as f:
            f.write(content)

        cli_main.run(["param", "set", "place.target_density", "0.7", "--project", project_dir])
        capsys.readouterr()

        with open(toml_path) as f:
            after = f.read()
        assert 'preset = "rtl2gds"' in after
        assert after.count("target_density") == 1


class TestMultilineTomlValues:
    """Scoped TOML edit must handle multiline array values."""

    def test_set_replaces_multiline_array(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += '\n[params.floorplan]\ncore_margin = [\n  2,\n  2,\n]\n'
        with open(toml_path, "w") as f:
            f.write(content)

        cli_main.run(["param", "set", "floorplan.core_margin", "[4, 4]", "--project", project_dir])
        capsys.readouterr()

        with open(toml_path) as f:
            after = f.read()
        assert "2," not in after
        assert after.count("core_margin") == 1
        assert "[4, 4]" in after

    def test_unset_removes_multiline_array(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += '\n[params.floorplan]\ncore_margin = [\n  2,\n  2,\n]\n'
        with open(toml_path, "w") as f:
            f.write(content)

        cli_main.run(["param", "unset", "floorplan.core_margin", "--project", project_dir])
        capsys.readouterr()

        with open(toml_path) as f:
            after = f.read()
        assert "core_margin" not in after

    def test_set_multiline_then_show(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += '\n[params.floorplan]\ncore_margin = [\n  2,\n  2,\n]\n'
        with open(toml_path, "w") as f:
            f.write(content)

        cli_main.run(["param", "set", "floorplan.core_margin", "[4, 4]", "--project", project_dir])
        capsys.readouterr()

        rc = cli_main.run(["param", "show", "floorplan.core_margin", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["value"] == [4, 4]

    def test_set_preserves_adjacent_key_after_multiline(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += '\n[params.floorplan]\ncore_margin = [\n  2,\n  2,\n]\n  core_util = 0.5\n'
        with open(toml_path, "w") as f:
            f.write(content)

        cli_main.run(["param", "set", "floorplan.core_margin", "[4, 4]", "--project", project_dir])
        capsys.readouterr()

        with open(toml_path) as f:
            after = f.read()
        assert "core_util = 0.5" in after
        assert after.count("core_margin") == 1
    """config --resolved must error on malformed/invalid CLI provenance."""

    def _setup_run_dir(self, project_dir):
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
        return run_dir

    def test_malformed_json_provenance_fails(self, tmp_path, capsys, monkeypatch):
        project_dir = _create_valid_project(tmp_path)
        run_dir = self._setup_run_dir(project_dir)
        with open(os.path.join(run_dir, "home", "cli-param-overrides.json"), "w") as f:
            f.write("not valid json{")
        monkeypatch.setattr(
            "chipcompiler.cli.config._validate_pdk_contents",
            lambda pdk_root, pdk_name: [],
        )
        rc = cli_main.run(["config", "--resolved", "--project", project_dir, "--json"])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["error"] == "invalid_config"

    def test_non_dict_provenance_fails(self, tmp_path, capsys, monkeypatch):
        project_dir = _create_valid_project(tmp_path)
        run_dir = self._setup_run_dir(project_dir)
        with open(os.path.join(run_dir, "home", "cli-param-overrides.json"), "w") as f:
            json.dump([1, 2, 3], f)
        monkeypatch.setattr(
            "chipcompiler.cli.config._validate_pdk_contents",
            lambda pdk_root, pdk_name: [],
        )
        rc = cli_main.run(["config", "--resolved", "--project", project_dir, "--json"])
        assert rc == 1

    def test_unknown_key_in_provenance_fails(self, tmp_path, capsys, monkeypatch):
        project_dir = _create_valid_project(tmp_path)
        run_dir = self._setup_run_dir(project_dir)
        with open(os.path.join(run_dir, "home", "cli-param-overrides.json"), "w") as f:
            json.dump({"nonexistent.param": 42}, f)
        monkeypatch.setattr(
            "chipcompiler.cli.config._validate_pdk_contents",
            lambda pdk_root, pdk_name: [],
        )
        rc = cli_main.run(["config", "--resolved", "--project", project_dir, "--json"])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["error"] == "invalid_config"


class TestParamShowDisclosureCommands:
    """param show must include disclosure command fields."""

    def test_show_json_has_disclosure_commands(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "show", "place.target_density", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        record = data["records"][0]
        assert "inspect" in record
        assert "set" in record
        assert "run" in record
        assert "ecc param show place.target_density" in record["inspect"]

    def test_show_text_has_disclosure_commands(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "show", "place.target_density", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "ecc param show place.target_density" in out
        assert "ecc param set place.target_density" in out
        assert "ecc run --set place.target_density" in out


class TestSafeTomlSectionParsing:
    """Scoped TOML edits must handle comments and indented headers safely."""

    def test_set_ignores_commented_section_header(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += '\n# [params.place]\n# target_density = 0.65\n'
        with open(toml_path, "w") as f:
            f.write(content)

        cli_main.run(["param", "set", "place.target_density", "0.7", "--project", project_dir])
        capsys.readouterr()

        with open(toml_path) as f:
            after = f.read()
        assert "[params.place]" in after
        assert "target_density = 0.7" in after

    def test_set_ignores_indented_next_section_header(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += '\n[params.place]\ntarget_density = 0.65\n\n  [flow]\npreset = "rtl2gds"\n'
        with open(toml_path, "w") as f:
            f.write(content)

        cli_main.run(["param", "set", "place.target_density", "0.7", "--project", project_dir])
        capsys.readouterr()

        with open(toml_path) as f:
            after = f.read()
        assert after.count("target_density") == 1
        assert "0.7" in after
        assert 'preset = "rtl2gds"' in after

    def test_set_then_show_after_commented_header(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += '\n# [params.place]\n# target_density = 0.65\n'
        with open(toml_path, "w") as f:
            f.write(content)

        cli_main.run(["param", "set", "place.target_density", "0.7", "--project", project_dir])
        capsys.readouterr()

        rc = cli_main.run(["param", "show", "place.target_density", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["value"] == 0.7

    def test_unset_ignores_commented_section_header(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += '\n# [params.place]\n# target_density = 0.65\n'
        with open(toml_path, "w") as f:
            f.write(content)

        rc = cli_main.run(["param", "unset", "place.target_density", "--project", project_dir])
        assert rc == 0
        capsys.readouterr()
        with open(toml_path) as f:
            after = f.read()
        assert "target_density" in after


class TestListDefaultDiffFiltering:
    """param diff must not report list values equal to defaults."""

    def test_list_default_not_in_diff(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        cli_main.run(["param", "set", "floorplan.core_margin", "[2,2]", "--project", project_dir])
        capsys.readouterr()

        rc = cli_main.run(["param", "diff", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0].get("diff_status") == "clean"

    def test_list_changed_value_in_diff(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        cli_main.run(["param", "set", "floorplan.core_margin", "[4,4]", "--project", project_dir])
        capsys.readouterr()

        rc = cli_main.run(["param", "diff", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data["records"]) >= 1
        margin = next((r for r in data["records"] if r.get("param") == "floorplan.core_margin"), None)
        assert margin is not None
        assert margin["value"] == [4, 4]


class TestZeroFrequencyRejected:
    """ecc param set design.frequency_mhz 0 must be rejected."""

    def test_set_zero_rejected(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run(["param", "set", "design.frequency_mhz", "0", "--project", project_dir])
        assert rc == 1

    def test_cli_set_zero_rejected(self, tmp_path):
        project_dir = _create_valid_project(tmp_path)
        rc = cli_main.run([
            "run", "--project", project_dir,
            "--set", "design.frequency_mhz=0",
        ])
        assert rc == 1


class TestDesignFrequencySeeded:
    """ecc param list/show must reflect [design] frequency_mhz."""

    def test_list_shows_design_frequency(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path, freq=200.0)
        rc = cli_main.run(["param", "list", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        freq = next(r for r in data["records"] if r["param"] == "design.frequency_mhz")
        assert freq["value"] == 200.0

    def test_show_shows_design_frequency(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path, freq=200.0)
        rc = cli_main.run(["param", "show", "design.frequency_mhz", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["value"] == 200.0

    def test_param_override_beats_design_frequency(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path, freq=200.0)
        cli_main.run(["param", "set", "design.frequency_mhz", "300", "--project", project_dir])
        capsys.readouterr()
        rc = cli_main.run(["param", "show", "design.frequency_mhz", "--project", project_dir, "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["value"] == 300.0
        assert data["records"][0]["source"] == "ecc.toml"


class TestMalformedTomlRejected:
    """ecc param list/show/diff must reject syntactically malformed ecc.toml."""

    def _write_malformed_toml(self, project_dir):
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path, "w") as f:
            f.write('[design\nname = "gcd"\n')

    def test_param_list_rejects_malformed(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        self._write_malformed_toml(project_dir)
        rc = cli_main.run(["param", "list", "--project", project_dir, "--json"])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["error"] == "invalid_param_config"

    def test_param_show_rejects_malformed(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        self._write_malformed_toml(project_dir)
        rc = cli_main.run(["param", "show", "design.frequency_mhz", "--project", project_dir, "--json"])
        assert rc == 1

    def test_param_diff_rejects_malformed(self, tmp_path, capsys):
        project_dir = _create_valid_project(tmp_path)
        self._write_malformed_toml(project_dir)
        rc = cli_main.run(["param", "diff", "--project", project_dir, "--json"])
        assert rc == 1
