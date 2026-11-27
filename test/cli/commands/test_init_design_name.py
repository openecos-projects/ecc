"""``ecc init`` writes the design name into ``ecc.toml`` as a TOML string."""

import json
import tomllib

import pytest

from chipcompiler.cli import main as cli_main

_NAMES = [
    'my"chip',
    "it's",
    "a\\db",  # a backslash that forms no TOML escape
    "a\\tb",  # a backslash that would form one
    "a\nb",
    "a\tb",
    "bell\x07",
    "del\x7f",
    "芯片 one",
    "a#b",
    "a = b",
    "{x}",
]


@pytest.mark.parametrize("name", _NAMES)
def test_init_writes_the_design_name_as_given(tmp_path, capsys, name):
    project = tmp_path / "project"

    assert cli_main.run(["init", str(project), "--design-name", name, "--plain"]) == 0

    design = tomllib.loads((project / "ecc.toml").read_text())["design"]
    assert (design["name"], design["top"]) == (name, name)
    manifest = json.loads((project / "project.json").read_text())
    assert manifest["design_name"] == name
    capsys.readouterr()


@pytest.mark.parametrize("directory", ['di"r', "back\\dslash", "tab\\there"])
def test_init_takes_the_design_name_from_the_directory_name(tmp_path, capsys, directory):
    project = tmp_path / directory

    assert cli_main.run(["init", str(project), "--plain"]) == 0

    design = tomllib.loads((project / "ecc.toml").read_text())["design"]
    assert design["name"] == directory
    assert design["top"] == directory
    capsys.readouterr()


def test_a_project_with_a_quoted_design_name_can_be_loaded(tmp_path, capsys, plain_records):
    project = tmp_path / "project"
    assert cli_main.run(["init", str(project), "--design-name", 'my"chip', "--plain"]) == 0
    capsys.readouterr()

    assert cli_main.run(["project", "show", "--project", str(project), "--plain"]) == 0

    records = plain_records(capsys.readouterr().out)
    assert "error" not in records[0]
    assert records[0]["project_field"] == "design.name"


def test_init_keeps_the_file_of_a_plain_name(tmp_path, capsys):
    project = tmp_path / "gcd"

    assert cli_main.run(["init", str(project), "--plain"]) == 0

    lines = (project / "ecc.toml").read_text().splitlines()
    assert lines[:3] == ["[design]", 'name = "gcd"', 'top = "gcd"']
    capsys.readouterr()
