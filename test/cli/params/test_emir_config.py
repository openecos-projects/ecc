"""External EMIR inputs use the regular parameter CLI and TOML persistence."""

import json
import tomllib

from chipcompiler.cli import main as cli_main


def test_emir_external_ploc_parameter_round_trip(ready_project):
    project = ["--project", str(ready_project)]
    technology = str(ready_project / "process.tech")
    ploc = str(ready_project.parent / "imported grid" / "power.ploc")
    assert cli_main.run(["param", "set", "emir.technology_file_path", technology, *project]) == 0
    assert cli_main.run(["param", "set", "emir.ploc_file_path", ploc, *project]) == 0

    config = tomllib.loads((ready_project / "ecc.toml").read_text())
    assert config["params"]["emir"] == {
        "technology_file_path": technology,
        "ploc_file_path": ploc,
    }

    assert cli_main.run(["param", "unset", "emir.ploc_file_path", *project]) == 0

    config = tomllib.loads((ready_project / "ecc.toml").read_text())
    assert config["params"]["emir"] == {"technology_file_path": technology}


def test_emir_supply_returns_round_trip(ready_project):
    project = ["--project", str(ready_project)]
    mapping = {"VDD": "VSS", "VDDD": "VSSD"}
    assert (
        cli_main.run(["param", "set", "emir.supply_ground_pins", json.dumps(mapping), *project])
        == 0
    )
    config = tomllib.loads((ready_project / "ecc.toml").read_text())
    assert config["params"]["emir"] == {"supply_ground_pins": mapping}
    assert cli_main.run(["param", "unset", "emir.supply_ground_pins", *project]) == 0
    config = tomllib.loads((ready_project / "ecc.toml").read_text())
    assert "supply_ground_pins" not in config.get("params", {}).get("emir", {})
