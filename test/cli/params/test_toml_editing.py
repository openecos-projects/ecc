import json
import os
import tomllib

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.project.toml_edit import remove_scoped_key, set_pdk_root, set_scoped_key


class TestSetPdkRoot:
    def test_set_pdk_root_escapes_quotes_and_backslashes(self):
        text = '[pdk]\nname = "ics55"\nroot = "/old"\n'

        result = set_pdk_root(text, 'C:\\pdk "special"')

        parsed = tomllib.loads(result)
        assert parsed["pdk"]["root"] == 'C:\\pdk "special"'
        assert parsed["pdk"]["name"] == "ics55"

    def test_set_pdk_root_creates_escaped_table_when_missing(self):
        result = set_pdk_root('name = "proj"\n', 'weird "path"\\dir')

        assert tomllib.loads(result)["pdk"]["root"] == 'weird "path"\\dir'


class TestScopedTomlEdit:
    def test_set_preserves_unrelated_sections(self, tmp_path, capsys, create_cli_project):
        project_dir = create_cli_project()
        toml_path = os.path.join(project_dir, "ecc.toml")
        with open(toml_path) as f:
            original = f.read()

        cli_main.run(["param", "set", "cts.max_fanout", "16", "--project", project_dir])
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

        cli_main.run(["param", "set", "cts.max_fanout", "16", "--project", project_dir])
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

    def test_set_then_show_still_works(self, tmp_path, capsys, create_cli_project, plain_records):
        project_dir = create_cli_project()

        cli_main.run(["param", "set", "place.target_density", "0.65", "--project", project_dir])
        capsys.readouterr()

        cli_main.run(["param", "set", "place.target_density", "0.7", "--project", project_dir])
        capsys.readouterr()

        rc = cli_main.run(
            ["param", "show", "place.target_density", "--project", project_dir, "--plain"]
        )
        assert rc == 0
        records = plain_records(capsys.readouterr().out)
        assert records[0]["value"] == "0.7"


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

    def test_set_then_show_indented(self, tmp_path, capsys, create_cli_project, plain_records):
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
            ["param", "show", "place.target_density", "--project", project_dir, "--plain"]
        )
        assert rc == 0
        records = plain_records(capsys.readouterr().out)
        assert records[0]["value"] == "0.7"

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

    def test_brackets_inside_strings_are_not_structure(self):
        import tomllib

        text = '[params.floorplan]\ntarget = "alu[rev"\nmode = "slide"\n'

        after = set_scoped_key(text, "params.floorplan", "target", "new")

        parsed = tomllib.loads(after)
        assert parsed["params"]["floorplan"] == {"target": "new", "mode": "slide"}

    def test_bracket_in_comment_does_not_swallow_keys(self):
        import tomllib

        text = '[params.floorplan]\ncore_margin = [2, 2] # [docs]\nmode = "slide"\n'

        after = set_scoped_key(text, "params.floorplan", "core_margin", [4, 4])

        parsed = tomllib.loads(after)
        assert parsed["params"]["floorplan"] == {"core_margin": [4, 4], "mode": "slide"}

    def test_unset_with_unbalanced_bracket_in_string(self):
        import tomllib

        text = '[pdk]\nroot = "a[\\b"\nname = "ics55"\n'

        after = remove_scoped_key(text, "pdk", "root")

        assert tomllib.loads(after) == {"pdk": {"name": "ics55"}}

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

    def test_set_multiline_then_show(self, tmp_path, capsys, create_cli_project, plain_records):
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
            ["param", "show", "floorplan.core_margin", "--project", project_dir, "--plain"]
        )
        assert rc == 0
        records = plain_records(capsys.readouterr().out)
        assert records[0]["value"] == "[4, 4]"

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

    """config must error on malformed/invalid CLI provenance."""

    def _setup_run_dir(self, project_dir):
        run_dir = os.path.join(project_dir, "default")
        os.makedirs(os.path.join(run_dir, "home"), exist_ok=True)
        return run_dir

    def test_malformed_json_provenance_fails(
        self,
        tmp_path,
        capsys,
        monkeypatch,
        create_cli_project,
        plain_records,
    ):
        project_dir = create_cli_project()
        run_dir = self._setup_run_dir(project_dir)
        with open(os.path.join(run_dir, "home", "cli-param-overrides.json"), "w") as f:
            f.write("not valid json{")
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: [],
        )
        rc = cli_main.run(["config", "--project", project_dir, "--plain"])
        assert rc == 1
        records = plain_records(capsys.readouterr().out)
        assert records[0]["error"] == "invalid_config"

    def test_non_dict_provenance_fails(self, tmp_path, capsys, monkeypatch, create_cli_project):
        project_dir = create_cli_project()
        run_dir = self._setup_run_dir(project_dir)
        with open(os.path.join(run_dir, "home", "cli-param-overrides.json"), "w") as f:
            json.dump([1, 2, 3], f)
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: [],
        )
        rc = cli_main.run(["config", "--project", project_dir, "--plain"])
        assert rc == 1

    def test_unknown_key_in_provenance_fails(
        self,
        tmp_path,
        capsys,
        monkeypatch,
        create_cli_project,
        plain_records,
    ):
        project_dir = create_cli_project()
        run_dir = self._setup_run_dir(project_dir)
        with open(os.path.join(run_dir, "home", "cli-param-overrides.json"), "w") as f:
            json.dump({"nonexistent.param": 42}, f)
        monkeypatch.setattr(
            "chipcompiler.cli.project.config._validate_pdk_contents",
            lambda name, root, overrides=None: [],
        )
        rc = cli_main.run(["config", "--project", project_dir, "--plain"])
        assert rc == 1
        records = plain_records(capsys.readouterr().out)
        assert records[0]["error"] == "invalid_config"


class TestSafeTomlSectionParsing:
    """Scoped TOML edits must handle comments and indented headers safely."""

    def test_set_does_not_insert_before_header_like_text_in_a_string(self):
        text = '[params]\nnote = """\nheader-like text:\n[flow]\n"""\n\n[pdk]\nname = "ics55"\n'

        result = set_scoped_key(text, "params.place", "target_density", 0.7)

        parsed = tomllib.loads(result)
        assert parsed["params"]["place"]["target_density"] == 0.7
        assert parsed["params"]["note"].strip() == "header-like text:\n[flow]"
        # The new table must land before the real [pdk] header, not the
        # header-like line inside the multiline string.
        assert result.index("[params.place]") > result.index('"""')

    def test_set_matches_quoted_table_header(self):
        text = '[params."place"]\ntarget_density = 0.65\n'

        result = set_scoped_key(text, "params.place", "target_density", 0.7)

        parsed = tomllib.loads(result)
        assert parsed["params"]["place"]["target_density"] == 0.7
        assert result.count("[params") == 1

    def test_set_replaces_quoted_assignment_key(self):
        text = '[params.place]\n"target_density" = 0.65\n'

        result = set_scoped_key(text, "params.place", "target_density", 0.7)

        parsed = tomllib.loads(result)
        assert parsed["params"]["place"]["target_density"] == 0.7
        assert result.count("target_density") == 1

    def test_unset_removes_quoted_assignment_key(self):
        text = '[params.place]\n"target_density" = 0.65\nother = 1\n'

        result = remove_scoped_key(text, "params.place", "target_density")

        parsed = tomllib.loads(result)
        assert "target_density" not in parsed["params"]["place"]
        assert parsed["params"]["place"]["other"] == 1

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

    def test_set_then_show_after_commented_header(
        self, tmp_path, capsys, create_cli_project, plain_records
    ):
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
            ["param", "show", "place.target_density", "--project", project_dir, "--plain"]
        )
        assert rc == 0
        records = plain_records(capsys.readouterr().out)
        assert records[0]["value"] == "0.7"

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
