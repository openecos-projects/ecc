"""Project-scope commands on per-step (DreamPlace) parameter values."""

from chipcompiler.cli import main as cli_main


def test_apply_writes_a_step_value_into_its_step_table(ready_project) -> None:
    rc = cli_main.run(
        [
            "param",
            "apply",
            "--project",
            str(ready_project),
            "--set",
            "placement:place.target_density=0.65",
        ]
    )

    assert rc == 0
    text = (ready_project / "ecc.toml").read_text(encoding="utf-8")
    assert "[params.step.placement.place]\ntarget_density = 0.65" in text


def test_show_list_and_diff_report_the_step_value(ready_project, capsys, plain_records) -> None:
    project = str(ready_project)
    assert (
        cli_main.run(
            ["param", "set", "placement:place.target_density", "0.65", "--project", project]
        )
        == 0
    )
    capsys.readouterr()

    cli_main.run(
        ["param", "show", "placement:place.target_density", "--project", project, "--plain"]
    )
    shown = plain_records(capsys.readouterr().out)[0]
    cli_main.run(["param", "list", "--step", "placement", "--project", project, "--plain"])
    listed = [
        record
        for record in plain_records(capsys.readouterr().out)
        if record["param"] == "place.target_density"
    ]
    cli_main.run(["param", "diff", "--project", project, "--plain"])
    diffed = [
        record
        for record in plain_records(capsys.readouterr().out)
        if record.get("param") == "placement:place.target_density"
    ]

    assert [(record["value"], record["source"]) for record in (shown, *listed, *diffed)] == [
        ("0.65", "ecc.toml"),
        ("0.65", "ecc.toml"),
        ("0.65", "ecc.toml"),
    ]
