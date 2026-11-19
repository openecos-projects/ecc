"""An invalid ecc.toml ``skip_steps`` is a config error on every command,
also when the selected workspace stores a skip list of its own."""

from pathlib import Path

import pytest

from chipcompiler.cli import main as cli_main

INVALID = [
    ('["nosuch"]', "skip_steps names unknown flow steps: nosuch"),
    # A step name is matched exactly: the former spelling is not a flow step.
    ('["drc", "Synthesis"]', "skip_steps names unknown flow steps: Synthesis"),
    ("[1, 2]", "skip_steps entries must be strings, not 1"),
    ('"lec"', "skip_steps must be a list, not str: 'lec'"),
]


@pytest.fixture
def project(create_cli_project, create_flow_json, manifest_stubs):
    """A project whose workspace entry stores a skip list, as after a first run."""
    project_dir = Path(create_cli_project())
    entry = manifest_stubs.entry(project_dir, "w1")
    entry["skip_steps"] = ["lec", "diff_opt"]
    manifest_stubs.write(project_dir, [entry])
    create_flow_json(str(project_dir / "w1"))

    def declare(value: str) -> str:
        with (project_dir / "ecc.toml").open("a") as config:
            config.write(f"skip_steps = {value}\n")
        return str(project_dir)

    return declare


@pytest.mark.parametrize(("value", "reason"), INVALID)
@pytest.mark.parametrize("selector", [[], ["--workspace", "w1"]])
def test_check_names_an_invalid_skip_list(project, capsys, plain_records, value, reason, selector):
    project_dir = project(value)

    rc = cli_main.run(["check", "--project", project_dir, *selector, "--plain"])

    assert rc == 1
    records = plain_records(capsys.readouterr().out)
    failures = [record["reason"] for record in records if record.get("check") == "config"]
    assert any(text.startswith(reason) for text in failures), records


@pytest.mark.parametrize(("value", "reason"), INVALID)
@pytest.mark.parametrize(
    "command",
    [["run", "--workspace", "w1"], ["workspace", "refresh", "w1"]],
    ids=["run", "refresh"],
)
def test_run_and_refresh_report_an_invalid_skip_list(
    project, capsys, plain_records, value, reason, command
):
    project_dir = project(value)

    rc = cli_main.run([*command, "--project", project_dir, "--plain"])

    assert rc == 1
    record = plain_records(capsys.readouterr().out)[-1]
    assert record["error"] == "config_error"
    assert record["reason"].startswith(reason)


@pytest.mark.parametrize(("value", "_reason"), INVALID)
def test_config_view_shows_a_project_with_an_invalid_skip_list(project, capsys, value, _reason):
    project_dir = project(value)

    # The view lists what is declared; validating it is the job of ecc check.
    assert cli_main.run(["config", "--project", project_dir, "--plain"]) == 0
    assert "config=flow.skip_steps" in capsys.readouterr().out
