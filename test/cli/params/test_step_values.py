"""Project-scope commands on per-step (DreamPlace) parameter values."""

import json
import shlex

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.data.step_parameters import is_step_scoped, split_step_key
from chipcompiler.params import lookup_schema


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


def test_show_needs_the_step_of_a_dreamplace_parameter(
    ready_project, capsys, plain_records
) -> None:
    rc = cli_main.run(
        ["param", "show", "place.target_density", "--project", str(ready_project), "--plain"]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert plain_records(captured.out + captured.err)[0]["error"] == "parameter_step_required"


def test_project_configuration_shows_explicit_step_values(
    create_cli_project, monkeypatch, capsys, plain_records
) -> None:
    project = create_cli_project()
    monkeypatch.setattr(
        "chipcompiler.cli.project.config._validate_pdk_contents",
        lambda name, root, overrides=None: None,
    )
    for step, value in (("placement", "up"), ("diff_opt", "quad")):
        key = f"{step}:place.timing_sizing_action"
        assert cli_main.run(["param", "set", key, value, "--project", project]) == 0
    capsys.readouterr()

    assert cli_main.run(["config", "--project", project, "--plain"]) == 0

    records = plain_records(capsys.readouterr().out)
    assert sorted(
        (record["key"], record["value"], record["source"])
        for record in records
        if record.get("kind") == "param" and "timing_sizing_action" in record["key"]
    ) == [
        ("diff_opt:place.timing_sizing_action", "quad", "ecc.toml"),
        ("placement:place.timing_sizing_action", "up", "ecc.toml"),
    ]


def test_step_list_inspects_step_scoped_parameters_at_the_step(
    ready_project, capsys, plain_records
) -> None:
    project = str(ready_project)
    assert (
        cli_main.run(
            ["param", "set", "placement:place.target_density", "0.65", "--project", project]
        )
        == 0
    )
    capsys.readouterr()

    assert (
        cli_main.run(["param", "list", "--step", "placement", "--project", project, "--plain"]) == 0
    )
    records = {record["param"]: record for record in plain_records(capsys.readouterr().out)}
    listed = [records["place.target_density"], records["place.random_seed"]]
    shown = []
    for record in listed:
        assert cli_main.run([*shlex.split(record["inspect"])[1:], "--plain"]) == 0
        shown.append(plain_records(capsys.readouterr().out)[0])

    assert [record["inspect"] for record in listed] == [
        f"ecc param show placement:place.target_density --project {project}",
        f"ecc param show placement:place.random_seed --project {project}",
    ]
    assert [(record["param"], record["value"], record["source"]) for record in shown] == [
        ("placement:place.target_density", "0.65", "ecc.toml"),
        ("placement:place.random_seed", records["place.random_seed"]["value"], "default"),
    ]


@pytest.mark.parametrize("extra", [["--plain"], ["--all", "--json"]])
def test_project_list_names_step_scoped_rows_by_step(
    ready_project, capsys, plain_records, extra
) -> None:
    project = str(ready_project)

    assert cli_main.run(["param", "list", "--project", project, *extra]) == 0
    out = capsys.readouterr().out
    records = plain_records(out) if "--plain" in extra else json.loads(out)
    step_scoped = [
        record
        for record in records
        if (schema := lookup_schema(split_step_key(record["param"])[1])) is not None
        and is_step_scoped(schema)
    ]
    failed = []
    for record in step_scoped:
        if cli_main.run([*shlex.split(record["inspect"])[1:], "--plain"]) != 0:
            failed.append(record["param"])
        capsys.readouterr()

    assert step_scoped
    assert all(split_step_key(record["param"])[0] for record in step_scoped)
    assert failed == []
