"""`ecc param` on a project: parameters spanning steps, and PDK-specific defaults."""

from pathlib import Path

from chipcompiler.cli import main as cli_main


class TestProjectParameterPdkAndSteps:
    def test_param_set_accepts_a_parameter_spanning_several_steps(self, create_cli_project, capsys):
        project_dir = create_cli_project()

        rc = cli_main.run(
            [
                "param",
                "set",
                "diff_opt:place.timing_sizing_action",
                "quad",
                "--project",
                project_dir,
            ]
        )

        assert rc == 0
        assert (
            '[params.step.diff_opt.place]\ntiming_sizing_action = "quad"'
            in (Path(project_dir) / "ecc.toml").read_text()
        )

    def test_param_list_step_filter_matches_every_step_a_parameter_names(
        self, create_cli_project, capsys, plain_records
    ):
        project_dir = create_cli_project()

        rc = cli_main.run(
            ["param", "list", "--all", "--step", "placement", "--project", project_dir, "--plain"]
        )

        assert rc == 0
        ids = {record["param"] for record in plain_records(capsys.readouterr().out)}
        assert "place.timing_sizing_action" in ids

    def test_param_show_reports_default_and_choices_for_the_project_pdk(
        self, create_cli_project, capsys, plain_records
    ):
        project_dir = create_cli_project()
        config = Path(project_dir) / "ecc.toml"
        config.write_text(config.read_text().replace('name = "ics55"', 'name = "sg13g2"'))

        rc = cli_main.run(
            ["param", "show", "route.bottom_layer", "--project", project_dir, "--plain"]
        )

        assert rc == 0
        (record,) = plain_records(capsys.readouterr().out)
        assert (record["default"], record["choices"]) == (
            "Metal2",
            "Metal1, Metal2, Metal3, Metal4, Metal5",
        )

    def test_param_show_reports_sg13g2_core_defaults(
        self, create_cli_project, capsys, plain_records
    ):
        project_dir = create_cli_project()
        config = Path(project_dir) / "ecc.toml"
        config.write_text(config.read_text().replace('name = "ics55"', 'name = "sg13g2"'))
        defaults = {}

        for param in ("floorplan.core_util", "floorplan.core_margin"):
            assert cli_main.run(["param", "show", param, "--project", project_dir, "--plain"]) == 0
            (record,) = plain_records(capsys.readouterr().out)
            defaults[param] = record["default"]

        assert defaults == {"floorplan.core_util": "0.65", "floorplan.core_margin": "[17.5, 17.5]"}
