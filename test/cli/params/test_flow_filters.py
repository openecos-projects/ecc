from chipcompiler.cli import main as cli_main


def test_param_list_synthesis_includes_global_parameters(capsys, create_cli_project, plain_records):
    project_dir = create_cli_project()
    rc = cli_main.run(["param", "list", "--step", "synthesis", "--project", project_dir, "--plain"])

    assert rc == 0
    assert [record["param"] for record in plain_records(capsys.readouterr().out)] == [
        "design.frequency_mhz",
        "flow.run_analysis",
    ]


def test_param_set_rejects_parameter_outside_project_flow(
    tmp_path, capsys, create_cli_project, plain_records
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


def test_param_list_excludes_steps_absent_from_selected_flow(
    tmp_path, capsys, create_cli_project, plain_records
):
    project_dir = create_cli_project()
    config_path = tmp_path / "gcd" / "ecc.toml"
    config_path.write_text(
        config_path.read_text().replace('preset = "rtl2gds"', 'preset = "synthesis_lec"')
    )

    rc = cli_main.run(["param", "list", "--step", "floorplan", "--project", project_dir, "--plain"])

    assert rc == 0
    assert plain_records(capsys.readouterr().out) == []


def test_param_list_default_excludes_explicit_absent_step_parameters(
    tmp_path, capsys, create_cli_project, plain_records
):
    project_dir = create_cli_project()
    config_path = tmp_path / "gcd" / "ecc.toml"
    config_path.write_text(
        config_path.read_text().replace('preset = "rtl2gds"', 'preset = "synthesis_lec"')
        + "\n[params.place]\ntarget_density = 0.65\n"
    )

    rc = cli_main.run(["param", "list", "--project", project_dir, "--plain"])

    assert rc == 0
    assert all(
        record["param"] != "place.target_density"
        for record in plain_records(capsys.readouterr().out)
    )
