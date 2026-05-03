import json
import os

from chipcompiler.cli import main as cli_main


def _create_valid_project(tmp_path, name="gcd", pdk_root=None):
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
frequency_mhz = 100.0

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
        assert record["default"] == 0.3
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
        assert "no_override" in out


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
        assert params.get("Target density") == 0.65

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
