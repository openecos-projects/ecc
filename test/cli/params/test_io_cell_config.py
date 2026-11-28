"""IO cell options use the normal nested parameter CLI and TOML persistence."""

import ast
import json
import tomllib

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.data.config_params.floorplan import pdn_defaults


def test_io_cell_parameter_batch_round_trip(ready_project):
    definition = ready_project / "io cells.json"
    definition.write_text("{}\n")
    prefix = "floorplan.io_placer"
    values = {
        f"{prefix}.mode": "io_cell",
        f"{prefix}.io_cell.definition_file_path": str(definition),
        f"{prefix}.io_cell.power.target_group_spacing": "750",
        f"{prefix}.io_cell.auto_resize.enable": "false",
        "floorplan.pdn_generator.core_power_net": "VDD_CORE",
        "floorplan.pdn_generator.core_ground_net": "VSS_CORE",
        "floorplan.pdn_generator.io_core_connect": json.dumps(
            {"enable": True, "fail_on_unresolved": True, "nets": ["VDD_CORE", "VSS_CORE"]}
        ),
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
    assert config["params"]["floorplan"]["pdn_generator"] == {
        "core_power_net": "VDD_CORE",
        "core_ground_net": "VSS_CORE",
        "io_core_connect": {
            "enable": True,
            "fail_on_unresolved": True,
            "nets": ["VDD_CORE", "VSS_CORE"],
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


def test_io_cell_mode_updates_displayed_pdn_defaults_and_preserves_explicit_mesh(
    ready_project, capsys, plain_records
):
    project = ["--project", str(ready_project)]
    mode_key = "floorplan.io_placer.mode"
    for mode in ("io_cell", "auto", "io_cell"):
        assert cli_main.run(["param", "set", mode_key, mode, *project]) == 0
        capsys.readouterr()
        for name, value in pdn_defaults("ics55", mode).items():
            key = f"floorplan.pdn_generator.{name}"
            assert cli_main.run(["param", "show", key, *project, "--plain"]) == 0
            record = plain_records(capsys.readouterr().out)[0]
            assert {
                "value": ast.literal_eval(record["value"]),
                "default": ast.literal_eval(record["default"]),
                "source": record["source"],
            } == {"value": value, "default": value, "source": "default"}

    core = pdn_defaults("ics55", "auto")
    for name, value in core.items():
        key = f"floorplan.pdn_generator.{name}"
        assert cli_main.run(["param", "set", key, json.dumps(value), *project]) == 0
        capsys.readouterr()
        assert cli_main.run(["param", "show", key, *project, "--plain"]) == 0
        record = plain_records(capsys.readouterr().out)[0]
        assert ast.literal_eval(record["value"]) == value
        assert record["source"] == "ecc.toml"

    assert (
        cli_main.run(["param", "unset", "floorplan.pdn_generator.stripe", *project, "--plain"]) == 0
    )
    record = plain_records(capsys.readouterr().out)[0]
    assert ast.literal_eval(record["value"]) == pdn_defaults("ics55", "io_cell")["stripe"]
    assert (
        cli_main.run(["param", "show", "floorplan.pdn_generator.stripe", *project, "--plain"]) == 0
    )
    record = plain_records(capsys.readouterr().out)[0]
    assert ast.literal_eval(record["value"]) == pdn_defaults("ics55", "io_cell")["stripe"]


def test_project_mesh_uses_configured_pdk_root(
    ready_project, tmp_path, monkeypatch, capsys, plain_records
):
    config = ready_project / "ecc.toml"
    raw = tomllib.loads(config.read_text())
    profile = tmp_path / "pdk" / "ecc-configs" / "ecc" / "floorplan_ecc.json"
    profile.parent.mkdir(parents=True)
    profile.write_text(json.dumps({"pdn_generator": {"stripe": []}}))
    config.write_text(config.read_text().replace(raw["pdk"]["root"], "../pdk"))
    environment = tmp_path / "other"
    environment.mkdir()
    (environment / "VERSION").write_text("other-pdk-v1\n")
    monkeypatch.setenv("ECC_PDK_ROOT", str(environment))

    project = ["--project", str(ready_project), "--plain"]
    assert cli_main.run(["param", "show", "design.frequency_mhz", *project]) == 0
    capsys.readouterr()
    assert cli_main.run(["param", "show", "floorplan.pdn_generator.stripe", *project]) == 0
    record = plain_records(capsys.readouterr().out)[0]
    assert (record["default"], record["value"], record["source"]) == ("[]", "[]", "default")
