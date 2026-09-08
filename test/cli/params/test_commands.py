import json
import os

from chipcompiler.cli import main as cli_main


class TestParamList:
    def test_param_list_text_output(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        rc = cli_main.run(["param", "list", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "place.target_density" in out

    def test_param_list_plain(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        rc = cli_main.run(["param", "list", "--project", project_dir, "--plain"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "\033[" not in out
        assert "place.target_density" in out

    def test_param_list_step_includes_config_schemas(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        rc = cli_main.run(["param", "list", "--step", "cts", "--project", project_dir])
        assert rc == 0
        assert "cts.skew_bound" in capsys.readouterr().out

    def test_param_list_synthesis_includes_global_parameters(
        self, tmp_path, capsys, create_cli_project, plain_records
    ):
        project_dir = create_cli_project()
        rc = cli_main.run(
            ["param", "list", "--step", "synthesis", "--project", project_dir, "--plain"]
        )

        assert rc == 0
        assert [record["param"] for record in plain_records(capsys.readouterr().out)] == [
            "design.frequency_mhz",
            "flow.run_analysis",
        ]


class TestParamShow:
    def test_param_show_known_key(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        rc = cli_main.run(["param", "show", "place.target_density", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "place.target_density" in out

    def test_param_show_records(self, tmp_path, capsys, create_cli_project, plain_records):
        project_dir = create_cli_project()
        rc = cli_main.run(
            ["param", "show", "place.target_density", "--project", project_dir, "--plain"]
        )
        assert rc == 0
        record = plain_records(capsys.readouterr().out)[0]
        assert record["param"] == "place.target_density"
        assert record["default"] == "0.2"
        assert "source" in record
        assert "maps_to" in record

    def test_param_show_unknown_key(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        rc = cli_main.run(["param", "show", "unknown.key", "--project", project_dir])
        assert rc == 1


class TestParamSet:
    def test_param_set_writes_toml(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        rc = cli_main.run(
            ["param", "set", "place.target_density", "0.65", "--project", project_dir]
        )
        assert rc == 0

        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        assert "target_density" in content
        assert "0.65" in content

    def test_param_set_then_show(self, tmp_path, capsys, create_cli_project, plain_records):
        project_dir = create_cli_project()
        cli_main.run(["param", "set", "place.target_density", "0.65", "--project", project_dir])
        capsys.readouterr()  # flush set output

        rc = cli_main.run(
            ["param", "show", "place.target_density", "--project", project_dir, "--plain"]
        )
        assert rc == 0
        record = plain_records(capsys.readouterr().out)[0]
        assert record["value"] == "0.65"
        assert record["source"] == "ecc.toml"

    def test_param_set_rejects_unknown_key(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        rc = cli_main.run(["param", "set", "bogus.key", "5", "--project", project_dir])
        assert rc == 1

    def test_param_set_rejects_invalid_value(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        rc = cli_main.run(["param", "set", "place.target_density", "1.5", "--project", project_dir])
        assert rc == 1

    def test_param_set_rejects_parameter_outside_project_flow(
        self, tmp_path, capsys, create_cli_project, plain_records
    ):
        project_dir = create_cli_project()
        config_path = tmp_path / "gcd" / "ecc.toml"
        config_path.write_text(
            config_path.read_text().replace('preset = "rtl2gds"', 'preset = "syn_sta"')
        )

        rc = cli_main.run(
            [
                "param",
                "set",
                "place.target_density",
                "0.65",
                "--project",
                project_dir,
                "--plain",
            ]
        )

        assert rc == 1
        assert plain_records(capsys.readouterr().out)[0]["error"] == "parameter_not_in_flow"
        assert "target_density" not in config_path.read_text()

    def test_param_set_accepts_negative_value(
        self, tmp_path, capsys, create_cli_project, plain_records
    ):
        project_dir = create_cli_project()
        rc = cli_main.run(
            ["param", "set", "--project", project_dir, "--plain", "place.max_net_weight", "-1"]
        )
        assert rc == 0
        record = plain_records(capsys.readouterr().out)[0]
        assert record["value"] == "-1"

    def test_param_set_preserves_other_sections(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        cli_main.run(["param", "set", "cts.max_fanout", "16", "--project", project_dir])

        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        assert "[design]" in content
        assert "[pdk]" in content
        assert "[flow]" in content

    def test_param_set_nested_config_writes_toml(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        rc = cli_main.run(
            [
                "param",
                "set",
                "floorplan.die_builder.mode",
                "die_size",
                "--project",
                project_dir,
            ]
        )
        assert rc == 0
        content = (tmp_path / "gcd" / "ecc.toml").read_text()
        assert "[params.floorplan.die_builder]" in content
        assert 'mode = "die_size"' in content

    def test_pdk_path_param_writes_pdk_overrides(
        self, tmp_path, monkeypatch, capsys, create_cli_project, plain_records
    ):
        project_dir = create_cli_project()
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )

        rc = cli_main.run(
            ["param", "set", "pdk.tech", "prtech/custom.lef", "--project", project_dir]
        )
        assert rc == 0

        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        assert "[pdk.overrides]" in content
        assert 'tech = "prtech/custom.lef"' in content
        capsys.readouterr()

        rc = cli_main.run(["param", "show", "pdk.tech", "--project", project_dir, "--plain"])
        assert rc == 0
        record = plain_records(capsys.readouterr().out)[0]
        assert record["value"] == "prtech/custom.lef"
        assert record["pdk_target"] == "pdk.overrides:tech"

        rc = cli_main.run(["param", "unset", "pdk.tech", "--project", project_dir])
        assert rc == 0
        with open(toml_path) as f:
            assert "tech =" not in f.read()


class TestParamUnset:
    def test_param_unset_removes_override(
        self, tmp_path, capsys, create_cli_project, plain_records
    ):
        project_dir = create_cli_project()
        cli_main.run(["param", "set", "place.target_density", "0.65", "--project", project_dir])
        capsys.readouterr()  # flush set output

        rc = cli_main.run(["param", "unset", "place.target_density", "--project", project_dir])
        assert rc == 0
        capsys.readouterr()  # flush unset output

        rc = cli_main.run(
            ["param", "show", "place.target_density", "--project", project_dir, "--plain"]
        )
        assert rc == 0
        record = plain_records(capsys.readouterr().out)[0]
        assert record["source"] == "default"

    def test_param_unset_noop_when_absent(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        rc = cli_main.run(["param", "unset", "place.target_density", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "no override" in out


class TestParamDiff:
    def test_param_diff_shows_overrides(self, tmp_path, capsys, create_cli_project, plain_records):
        project_dir = create_cli_project()
        cli_main.run(["param", "set", "place.target_density", "0.65", "--project", project_dir])
        capsys.readouterr()  # flush set output

        rc = cli_main.run(["param", "diff", "--project", project_dir, "--plain"])
        assert rc == 0
        records = plain_records(capsys.readouterr().out)
        assert len(records) == 1
        assert records[0]["param"] == "place.target_density"

    def test_param_diff_clean_when_no_overrides(
        self, tmp_path, capsys, create_cli_project, plain_records
    ):
        project_dir = create_cli_project()
        rc = cli_main.run(["param", "diff", "--project", project_dir, "--plain"])
        assert rc == 0
        records = plain_records(capsys.readouterr().out)
        assert records[0].get("diff_status") == "clean"


class TestRunSet:
    def test_run_set_override(self, tmp_path, monkeypatch, capsys, create_cli_project):
        from types import SimpleNamespace

        project_dir = create_cli_project()
        workspace_obj = SimpleNamespace(name="workspace")
        capture = {"kwargs": None}

        def fake_create(**kwargs):
            capture["kwargs"] = kwargs
            return workspace_obj

        monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create)
        monkeypatch.setattr(
            "chipcompiler.engine.EngineFlow",
            type(
                "DummyFlow",
                (),
                {
                    "__init__": lambda self, workspace: None,
                    "has_init": lambda self: False,
                    "add_step": lambda self, **kw: None,
                    "create_step_workspaces": lambda self: None,
                    "run_steps": lambda self: True,
                },
            ),
        )
        monkeypatch.setattr(
            "chipcompiler.rtl2gds.builder.build_rtl2gds_flow",
            lambda: [("Synthesis", "yosys", "Unstart")],
        )
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )
        monkeypatch.setattr(
            "chipcompiler.cli.rendering.progress.should_enable_run_progress",
            lambda *a, **kw: False,
        )

        rc = cli_main.run(
            [
                "run",
                "--project",
                project_dir,
                "--set",
                "place.target_density=0.65",
            ]
        )
        assert rc == 0

        params = capture["kwargs"]["parameters"]
        assert params.get("dreamplace", {}).get("target_density") == 0.65

    def test_run_set_direct_config_and_pdk_overrides(
        self, tmp_path, monkeypatch, capsys, create_cli_project
    ):
        from types import SimpleNamespace

        project_dir = create_cli_project()
        capture = {"kwargs": None}

        def fake_create(**kwargs):
            capture["kwargs"] = kwargs
            return SimpleNamespace(name="workspace")

        monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create)
        monkeypatch.setattr(
            "chipcompiler.engine.EngineFlow",
            type(
                "DummyFlow",
                (),
                {
                    "__init__": lambda self, workspace: None,
                    "has_init": lambda self: False,
                    "add_step": lambda self, **kw: None,
                    "create_step_workspaces": lambda self: None,
                    "run_steps": lambda self: True,
                },
            ),
        )
        monkeypatch.setattr(
            "chipcompiler.rtl2gds.builder.build_rtl2gds_flow",
            lambda: [("Synthesis", "yosys", "Unstart")],
        )
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )
        monkeypatch.setattr(
            "chipcompiler.cli.rendering.progress.should_enable_run_progress",
            lambda *a, **kw: False,
        )

        rc = cli_main.run(
            [
                "run",
                "--project",
                project_dir,
                "--set",
                "cts.skew_bound=0.05",
                "--set",
                "pdk.tech=prtech/custom.lef",
            ]
        )
        assert rc == 0

        params = capture["kwargs"]["parameters"]
        assert params["config_overrides"] == {"CTS": {"skew_bound": "0.05"}}
        assert capture["kwargs"]["pdk_overrides"]["tech"].endswith("prtech/custom.lef")

    def test_run_set_rejects_unknown_key(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        rc = cli_main.run(
            [
                "run",
                "--project",
                project_dir,
                "--set",
                "bogus.key=5",
            ]
        )
        assert rc == 1

    def test_run_set_rejects_invalid_value(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        rc = cli_main.run(
            [
                "run",
                "--project",
                project_dir,
                "--set",
                "place.target_density=1.5",
            ]
        )
        assert rc == 1

    def test_run_set_does_not_modify_toml(self, tmp_path, monkeypatch, capsys, create_cli_project):
        from types import SimpleNamespace

        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            original_toml = f.read()

        workspace_obj = SimpleNamespace(name="workspace")

        def fake_create(**kwargs):
            return workspace_obj

        monkeypatch.setattr("chipcompiler.data.create_workspace", fake_create)
        monkeypatch.setattr(
            "chipcompiler.engine.EngineFlow",
            type(
                "DummyFlow",
                (),
                {
                    "__init__": lambda self, workspace: None,
                    "has_init": lambda self: False,
                    "add_step": lambda self, **kw: None,
                    "create_step_workspaces": lambda self: None,
                    "run_steps": lambda self: True,
                },
            ),
        )
        monkeypatch.setattr(
            "chipcompiler.rtl2gds.builder.build_rtl2gds_flow",
            lambda: [("Synthesis", "yosys", "Unstart")],
        )
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )
        monkeypatch.setattr(
            "chipcompiler.cli.rendering.progress.should_enable_run_progress",
            lambda *a, **kw: False,
        )

        cli_main.run(
            [
                "run",
                "--project",
                project_dir,
                "--set",
                "place.target_density=0.65",
            ]
        )

        with open(toml_path) as f:
            current_toml = f.read()
        assert current_toml == original_toml


class TestOutputContracts:
    def test_plain_no_ansi(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        rc = cli_main.run(["param", "list", "--project", project_dir, "--plain"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "\033[" not in out

    def test_plain_is_line_oriented(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        rc = cli_main.run(["param", "list", "--project", project_dir, "--plain"])
        assert rc == 0
        out = capsys.readouterr().out
        lines = [line for line in out.strip().split("\n") if line.strip()]
        assert len(lines) == 14


class TestConfigResolved:
    def test_config_resolved_includes_param_records(
        self, tmp_path, monkeypatch, capsys, create_cli_project, plain_records
    ):
        project_dir = create_cli_project()
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )
        run_dir = os.path.join(project_dir, "runs", "default")
        home = os.path.join(run_dir, "home")
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(home, "flow.json"), "w") as f:
            json.dump({"steps": []}, f)

        rc = cli_main.run(["config", "--project", project_dir, "--plain"])
        assert rc == 0
        records = plain_records(capsys.readouterr().out)
        param_records = [r for r in records if r.get("kind") == "param"]
        assert len(param_records) == 14
        first_param = param_records[0]
        assert "source" in first_param
        assert "maps_to" in first_param

    def test_config_resolved_shows_toml_source(
        self, tmp_path, monkeypatch, capsys, create_cli_project, plain_records
    ):
        project_dir = create_cli_project()
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )
        cli_main.run(["param", "set", "place.target_density", "0.65", "--project", project_dir])
        capsys.readouterr()  # flush set output

        run_dir = os.path.join(project_dir, "runs", "default")
        home = os.path.join(run_dir, "home")
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(home, "flow.json"), "w") as f:
            json.dump({"steps": []}, f)

        rc = cli_main.run(["config", "--project", project_dir, "--plain"])
        assert rc == 0
        param_records = [
            r for r in plain_records(capsys.readouterr().out) if r.get("kind") == "param"
        ]
        density = next(r for r in param_records if r["key"] == "place.target_density")
        assert density["value"] == "0.65"
        assert density["source"] == "ecc.toml"

    def test_config_resolved_seeds_design_frequency(
        self, tmp_path, monkeypatch, capsys, create_cli_project, plain_records
    ):
        project_dir = create_cli_project(freq=200.0)
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: None,
        )
        run_dir = os.path.join(project_dir, "runs", "default")
        home = os.path.join(run_dir, "home")
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(home, "flow.json"), "w") as f:
            json.dump({"steps": []}, f)

        rc = cli_main.run(["config", "--project", project_dir, "--plain"])
        assert rc == 0
        param_records = [
            r for r in plain_records(capsys.readouterr().out) if r.get("kind") == "param"
        ]
        freq = next(r for r in param_records if r["key"] == "design.frequency_mhz")
        assert freq["value"] == "200.0"


class TestPrettyOutput:
    def test_param_list_default_is_grouped_text(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        rc = cli_main.run(["param", "list", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "place" in out
        assert "place.target_density" in out

    def test_param_list_plain_is_one_line_per_record(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        rc = cli_main.run(["param", "list", "--project", project_dir, "--plain"])
        assert rc == 0
        out = capsys.readouterr().out
        lines = [line for line in out.strip().split("\n") if line.strip()]
        assert len(lines) == 14
        assert "\033[" not in out

    def test_param_show_default_is_pretty(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        rc = cli_main.run(["param", "show", "place.target_density", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "place.target_density" in out
        assert "source" in out
        assert "default" in out

    def test_param_set_default_is_pretty(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        rc = cli_main.run(
            ["param", "set", "place.target_density", "0.65", "--project", project_dir]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "0.65" in out

    def test_param_diff_default_is_pretty(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        cli_main.run(["param", "set", "place.target_density", "0.65", "--project", project_dir])
        capsys.readouterr()
        rc = cli_main.run(["param", "diff", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "place.target_density" in out


class TestResolvedListValues:
    def test_param_list_records_have_value_and_source(
        self, tmp_path, capsys, create_cli_project, plain_records
    ):
        project_dir = create_cli_project()
        cli_main.run(["param", "set", "place.target_density", "0.65", "--project", project_dir])
        capsys.readouterr()

        rc = cli_main.run(["param", "list", "--project", project_dir, "--plain"])
        assert rc == 0
        records = plain_records(capsys.readouterr().out)
        density = next(r for r in records if r["param"] == "place.target_density")
        assert density["value"] == "0.65"
        assert density["source"] == "ecc.toml"
        assert "default" in density
        assert "maps_to" in density
        assert "inspect" in density

    def test_param_list_default_source_when_no_overrides(
        self, tmp_path, capsys, create_cli_project, plain_records
    ):
        project_dir = create_cli_project()
        rc = cli_main.run(["param", "list", "--project", project_dir, "--plain"])
        assert rc == 0
        for r in plain_records(capsys.readouterr().out):
            if r["param"] == "design.frequency_mhz":
                assert r["source"] == "ecc.toml"
            else:
                assert r["source"] == "default"


class TestDiffFiltering:
    def test_diff_only_shows_values_that_differ(
        self, tmp_path, capsys, create_cli_project, plain_records
    ):
        project_dir = create_cli_project()
        cli_main.run(["param", "set", "place.target_density", "0.65", "--project", project_dir])
        capsys.readouterr()

        rc = cli_main.run(["param", "diff", "--project", project_dir, "--plain"])
        assert rc == 0
        records = plain_records(capsys.readouterr().out)
        assert len(records) == 1
        assert records[0]["param"] == "place.target_density"
        assert records[0]["value"] == "0.65"
        assert records[0]["default"] != records[0]["value"]

    def test_diff_clean_when_set_to_default(
        self, tmp_path, capsys, create_cli_project, plain_records
    ):
        project_dir = create_cli_project()
        schema_default = 0.2
        cli_main.run(
            ["param", "set", "place.target_density", str(schema_default), "--project", project_dir]
        )
        capsys.readouterr()

        rc = cli_main.run(["param", "diff", "--project", project_dir, "--plain"])
        assert rc == 0
        records = plain_records(capsys.readouterr().out)
        assert records[0].get("diff_status") == "clean"


class TestParamShowDisclosureCommands:
    """param show must include disclosure command fields."""

    def test_show_records_have_disclosure_commands(
        self, tmp_path, capsys, create_cli_project, plain_records
    ):
        project_dir = create_cli_project()
        rc = cli_main.run(
            ["param", "show", "place.target_density", "--project", project_dir, "--plain"]
        )
        assert rc == 0
        record = plain_records(capsys.readouterr().out)[0]
        assert "inspect" in record
        assert "set" in record
        assert "run" in record
        assert "ecc param show place.target_density" in record["inspect"]

    def test_show_text_has_disclosure_commands(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        rc = cli_main.run(["param", "show", "place.target_density", "--project", project_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "ecc param show place.target_density" in out
        assert "ecc param set place.target_density" in out
        assert "ecc run --set place.target_density" in out


class TestListDefaultDiffFiltering:
    """param diff must not report list values equal to defaults."""

    def test_list_default_not_in_diff(self, tmp_path, capsys, create_cli_project, plain_records):
        project_dir = create_cli_project()
        cli_main.run(["param", "set", "floorplan.core_margin", "[2,2]", "--project", project_dir])
        capsys.readouterr()

        rc = cli_main.run(["param", "diff", "--project", project_dir, "--plain"])
        assert rc == 0
        records = plain_records(capsys.readouterr().out)
        assert records[0].get("diff_status") == "clean"

    def test_list_changed_value_in_diff(self, tmp_path, capsys, create_cli_project, plain_records):
        project_dir = create_cli_project()
        cli_main.run(["param", "set", "floorplan.core_margin", "[4,4]", "--project", project_dir])
        capsys.readouterr()

        rc = cli_main.run(["param", "diff", "--project", project_dir, "--plain"])
        assert rc == 0
        records = plain_records(capsys.readouterr().out)
        assert len(records) >= 1
        margin = next((r for r in records if r.get("param") == "floorplan.core_margin"), None)
        assert margin is not None
        assert margin["value"] == "[4, 4]"


class TestDesignFrequencySeeded:
    """ecc param list/show must reflect [design] frequency_mhz."""

    def test_list_shows_design_frequency(self, tmp_path, capsys, create_cli_project, plain_records):
        project_dir = create_cli_project(freq=200.0)
        rc = cli_main.run(["param", "list", "--project", project_dir, "--plain"])
        assert rc == 0
        freq = next(
            r
            for r in plain_records(capsys.readouterr().out)
            if r["param"] == "design.frequency_mhz"
        )
        assert freq["value"] == "200.0"

    def test_show_shows_design_frequency(self, tmp_path, capsys, create_cli_project, plain_records):
        project_dir = create_cli_project(freq=200.0)
        rc = cli_main.run(
            ["param", "show", "design.frequency_mhz", "--project", project_dir, "--plain"]
        )
        assert rc == 0
        records = plain_records(capsys.readouterr().out)
        assert records[0]["value"] == "200.0"

    def test_param_override_beats_design_frequency(
        self, tmp_path, capsys, create_cli_project, plain_records
    ):
        project_dir = create_cli_project(freq=200.0)
        cli_main.run(["param", "set", "design.frequency_mhz", "300", "--project", project_dir])
        capsys.readouterr()
        rc = cli_main.run(
            ["param", "show", "design.frequency_mhz", "--project", project_dir, "--plain"]
        )
        assert rc == 0
        records = plain_records(capsys.readouterr().out)
        assert records[0]["value"] == "300.0"
        assert records[0]["source"] == "ecc.toml"
