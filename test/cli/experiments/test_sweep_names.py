import json

import pytest
from typer.testing import CliRunner

from chipcompiler.cli.app import app
from chipcompiler.cli.experiments import operations

UNSAFE_NAMES = ["../escape", "..", ".", ".hidden", "nested/name", "back\\slash", "", "a b"]


@pytest.mark.parametrize("name", ["param-search-1", "sweep_2", "v1.2", "-leading-dash"])
def test_sweep_root_accepts_plain_identifiers(tmp_path, name):
    assert operations.sweep_root(tmp_path, name) == tmp_path / "experiments" / name


@pytest.mark.parametrize("name", UNSAFE_NAMES)
def test_sweep_root_rejects_names_that_are_not_plain_identifiers(tmp_path, name):
    with pytest.raises(ValueError, match="invalid sweep name"):
        operations.sweep_root(tmp_path, name)


def test_sweep_root_rejects_absolute_path(tmp_path):
    with pytest.raises(ValueError, match="invalid sweep name"):
        operations.sweep_root(tmp_path, str(tmp_path / "absolute"))


def _create(project, name):
    return CliRunner().invoke(
        app,
        [
            "sweep",
            "create",
            "--project",
            str(project),
            "--name",
            name,
            "--param",
            "place.target_density=0.5,0.6",
        ],
    )


def test_sweep_create_rejects_parent_traversal(tmp_path):
    project = tmp_path / "project"
    project.mkdir()

    result = _create(project, "../escape")

    assert result.exit_code == 2
    assert "invalid sweep name" in result.output
    assert not (project / "escape").exists()
    assert not (project / "experiments").exists()


def test_sweep_create_rejects_absolute_path(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "absolute"

    result = _create(project, str(outside))

    assert result.exit_code == 2
    assert "invalid sweep name" in result.output
    assert not outside.exists()


def test_sweep_create_still_accepts_plain_name(tmp_path):
    project = tmp_path / "project"
    project.mkdir()

    result = _create(project, "param-search-1")

    assert result.exit_code == 0
    plan = json.loads((project / "experiments" / "param-search-1" / "sweep.json").read_text())
    assert plan["name"] == "param-search-1"
    assert len(plan["candidates"]) == 2


@pytest.mark.parametrize(
    "command",
    [
        ["sweep", "show"],
        ["sweep", "run"],
        ["sweep", "compare"],
        ["sweep", "verify"],
        ["explore", "rank"],
        ["explore", "export"],
        ["explore", "promote", "--candidate", "candidate_0001"],
    ],
)
def test_sweep_commands_reject_traversal_names(tmp_path, command):
    project = tmp_path / "project"
    project.mkdir()

    result = CliRunner().invoke(app, [*command, "--project", str(project), "--name", "../escape"])

    assert result.exit_code == 2
    assert "invalid sweep name" in result.output
    assert not (project / "escape").exists()
