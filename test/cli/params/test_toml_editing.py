import json
import os

from chipcompiler.cli import main as cli_main


class TestScopedTomlEdit:
    def test_set_preserves_unrelated_sections(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            original = f.read()

        cli_main.run(["param", "set", "synth.max_fanout", "16", "--project", project_dir])
        capsys.readouterr()

        with open(toml_path) as f:
            after = f.read()
        design_section = original[original.index("[design]") : original.index("[pdk]")]
        assert design_section in after

    def test_set_preserves_comments(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
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

    def test_set_same_key_twice_has_one_assignment(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
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

    def test_set_then_show_still_works(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()

        cli_main.run(["param", "set", "place.target_density", "0.65", "--project", project_dir])
        capsys.readouterr()

        cli_main.run(["param", "set", "place.target_density", "0.7", "--project", project_dir])
        capsys.readouterr()

        rc = cli_main.run(
            ["param", "show", "place.target_density", "--project", project_dir, "--json"]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["value"] == 0.7


class TestIndentedTomlKeys:
    """Scoped TOML edit must handle indented assignment lines."""

    def test_set_replaces_indented_key(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += "\n[params.place]\n  target_density = 0.65\n"
        with open(toml_path, "w") as f:
            f.write(content)

        cli_main.run(["param", "set", "place.target_density", "0.7", "--project", project_dir])
        capsys.readouterr()

        with open(toml_path) as f:
            after = f.read()
        assert after.count("target_density") == 1
        assert "0.7" in after

    def test_set_then_show_indented(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += "\n[params.place]\n  target_density = 0.65\n"
        with open(toml_path, "w") as f:
            f.write(content)

        cli_main.run(["param", "set", "place.target_density", "0.7", "--project", project_dir])
        capsys.readouterr()

        rc = cli_main.run(
            ["param", "show", "place.target_density", "--project", project_dir, "--json"]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["value"] == 0.7

    def test_unset_removes_indented_key(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += "\n[params.place]\n  target_density = 0.65\n"
        with open(toml_path, "w") as f:
            f.write(content)

        cli_main.run(["param", "unset", "place.target_density", "--project", project_dir])
        capsys.readouterr()

        with open(toml_path) as f:
            after = f.read()
        assert "target_density" not in after

    def test_set_indented_preserves_other_sections(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
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

    def test_set_replaces_multiline_array(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += "\n[params.floorplan]\ncore_margin = [\n  2,\n  2,\n]\n"
        with open(toml_path, "w") as f:
            f.write(content)

        cli_main.run(["param", "set", "floorplan.core_margin", "[4, 4]", "--project", project_dir])
        capsys.readouterr()

        with open(toml_path) as f:
            after = f.read()
        assert "2," not in after
        assert after.count("core_margin") == 1
        assert "[4, 4]" in after

    def test_unset_removes_multiline_array(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += "\n[params.floorplan]\ncore_margin = [\n  2,\n  2,\n]\n"
        with open(toml_path, "w") as f:
            f.write(content)

        cli_main.run(["param", "unset", "floorplan.core_margin", "--project", project_dir])
        capsys.readouterr()

        with open(toml_path) as f:
            after = f.read()
        assert "core_margin" not in after

    def test_set_multiline_then_show(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += "\n[params.floorplan]\ncore_margin = [\n  2,\n  2,\n]\n"
        with open(toml_path, "w") as f:
            f.write(content)

        cli_main.run(["param", "set", "floorplan.core_margin", "[4, 4]", "--project", project_dir])
        capsys.readouterr()

        rc = cli_main.run(
            ["param", "show", "floorplan.core_margin", "--project", project_dir, "--json"]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["value"] == [4, 4]

    def test_set_preserves_adjacent_key_after_multiline(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += "\n[params.floorplan]\ncore_margin = [\n  2,\n  2,\n]\n  core_util = 0.5\n"
        with open(toml_path, "w") as f:
            f.write(content)

        cli_main.run(["param", "set", "floorplan.core_margin", "[4, 4]", "--project", project_dir])
        capsys.readouterr()

        with open(toml_path) as f:
            after = f.read()
        assert "core_util = 0.5" in after
        assert after.count("core_margin") == 1
        for line in after.splitlines():
            assert "core_margin" not in line or "core_util" not in line, (
                f"multiline replacement concatenated keys on one line: {line!r}"
            )

    """config --resolved must error on malformed/invalid CLI provenance."""

    def _setup_run_dir(self, project_dir):
        run_dir = os.path.join(project_dir, "runs", "default")
        os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
        return run_dir

    def test_malformed_json_provenance_fails(
        self, tmp_path, capsys, monkeypatch, create_cli_project
    ):
        project_dir = create_cli_project()
        run_dir = self._setup_run_dir(project_dir)
        with open(os.path.join(run_dir, "home", "cli-param-overrides.json"), "w") as f:
            f.write("not valid json{")
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda pdk_root, pdk_name: [],
        )
        rc = cli_main.run(["config", "--resolved", "--project", project_dir, "--json"])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["error"] == "invalid_config"

    def test_non_dict_provenance_fails(self, tmp_path, capsys, monkeypatch, create_cli_project):
        project_dir = create_cli_project()
        run_dir = self._setup_run_dir(project_dir)
        with open(os.path.join(run_dir, "home", "cli-param-overrides.json"), "w") as f:
            json.dump([1, 2, 3], f)
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda pdk_root, pdk_name: [],
        )
        rc = cli_main.run(["config", "--resolved", "--project", project_dir, "--json"])
        assert rc == 1

    def test_unknown_key_in_provenance_fails(
        self, tmp_path, capsys, monkeypatch, create_cli_project
    ):
        project_dir = create_cli_project()
        run_dir = self._setup_run_dir(project_dir)
        with open(os.path.join(run_dir, "home", "cli-param-overrides.json"), "w") as f:
            json.dump({"nonexistent.param": 42}, f)
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda pdk_root, pdk_name: [],
        )
        rc = cli_main.run(["config", "--resolved", "--project", project_dir, "--json"])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["error"] == "invalid_config"


class TestSafeTomlSectionParsing:
    """Scoped TOML edits must handle comments and indented headers safely."""

    def test_set_ignores_commented_section_header(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += "\n# [params.place]\n# target_density = 0.65\n"
        with open(toml_path, "w") as f:
            f.write(content)

        cli_main.run(["param", "set", "place.target_density", "0.7", "--project", project_dir])
        capsys.readouterr()

        with open(toml_path) as f:
            after = f.read()
        assert "[params.place]" in after
        assert "target_density = 0.7" in after

    def test_set_ignores_indented_next_section_header(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
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

    def test_set_then_show_after_commented_header(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += "\n# [params.place]\n# target_density = 0.65\n"
        with open(toml_path, "w") as f:
            f.write(content)

        cli_main.run(["param", "set", "place.target_density", "0.7", "--project", project_dir])
        capsys.readouterr()

        rc = cli_main.run(
            ["param", "show", "place.target_density", "--project", project_dir, "--json"]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["records"][0]["value"] == 0.7

    def test_unset_ignores_commented_section_header(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            content = f.read()
        content += "\n# [params.place]\n# target_density = 0.65\n"
        with open(toml_path, "w") as f:
            f.write(content)

        rc = cli_main.run(["param", "unset", "place.target_density", "--project", project_dir])
        assert rc == 0
        capsys.readouterr()
        with open(toml_path) as f:
            after = f.read()
        assert "target_density" in after
