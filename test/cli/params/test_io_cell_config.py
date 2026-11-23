"""IO cell options use the normal nested parameter CLI and TOML persistence."""

import tomllib

import pytest

from chipcompiler.cli import main as cli_main


def test_io_cell_parameter_batch_round_trip(ready_project):
    definition = ready_project / "io cells.json"
    definition.write_text("{}\n")
    prefix = "floorplan.io_placer"
    values = {
        f"{prefix}.mode": "io_cell",
        f"{prefix}.io_cell.definition_file_path": str(definition),
        f"{prefix}.io_cell.power.target_group_spacing": "750",
        f"{prefix}.io_cell.auto_resize.enable": "false",
    }
    command = ["param", "apply", "--project", str(ready_project)]
    for key, value in values.items():
        command.extend(["--set", f"{key}={value}"])

    assert cli_main.run(command) == 0
    config = tomllib.loads((ready_project / "ecc.toml").read_text())
    assert config["params"]["floorplan"]["io_placer"] == {
        "mode": "io_cell",
        "io_cell": {
            "definition_file_path": str(definition),
            "power": {"target_group_spacing": 750.0},
            "auto_resize": {"enable": False},
        },
    }

    assert (
        cli_main.run(
            ["param", "apply", "--project", str(ready_project), "--unset", f"{prefix}.mode"]
        )
        == 0
    )
    config = tomllib.loads((ready_project / "ecc.toml").read_text())
    assert config["params"]["floorplan"]["io_placer"] == {
        "io_cell": {
            "definition_file_path": str(definition),
            "power": {"target_group_spacing": 750.0},
            "auto_resize": {"enable": False},
        }
    }


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("floorplan.io_placer.mode", "unsupported"),
        ("floorplan.io_placer.io_cell.auto_resize.enable", "sometimes"),
    ],
)
def test_invalid_io_cell_parameter_does_not_change_project(ready_project, key, value):
    manifest = ready_project / "ecc.toml"
    before = manifest.read_bytes()

    assert cli_main.run(["param", "set", key, value, "--project", str(ready_project)]) == 1

    assert manifest.read_bytes() == before
