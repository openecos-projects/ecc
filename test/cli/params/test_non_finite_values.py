"""``nan`` and infinities are refused by every way of setting a parameter."""

import os

import pytest

from chipcompiler.cli import main as cli_main

_CASES = [
    ("design.frequency_mhz", "nan"),
    ("floorplan.core_util", "NaN"),
    ("floorplan.core_util", "-nan"),
    ("placement:place.target_density", "nan"),
    ("floorplan.core_util", "inf"),
    ("floorplan.macro_placer.macro_placement_halo", "nan"),
    ("floorplan.macro_placer.macro_placement_halo", "inf"),
    ("floorplan.macro_placer.macro_placement_halo", "-inf"),
    ("floorplan.core_margin", "nan,2"),
    ("floorplan.core_margin", "2,inf"),
]


def _toml(project_dir: str) -> str:
    with open(os.path.join(project_dir, "ecc.toml")) as handle:
        return handle.read()


@pytest.mark.parametrize(("key", "raw"), _CASES)
def test_param_set_refuses_a_non_finite_value(capsys, create_cli_project, plain_records, key, raw):
    project_dir = create_cli_project()
    before = _toml(project_dir)

    rc = cli_main.run(["param", "set", key, raw, "--project", project_dir, "--plain"])

    assert rc == 1
    record = plain_records(capsys.readouterr().out)[0]
    assert record["error"] == "invalid_value"
    assert _toml(project_dir) == before


def test_param_apply_refuses_the_batch_and_writes_nothing(capsys, create_cli_project):
    project_dir = create_cli_project()
    before = _toml(project_dir)

    rc = cli_main.run(
        [
            "param",
            "apply",
            "--set",
            "floorplan.core_util=0.6",
            "--set",
            "design.frequency_mhz=nan",
            "--project",
            project_dir,
            "--plain",
        ]
    )

    assert rc == 1
    assert "not a finite number" in capsys.readouterr().out
    assert _toml(project_dir) == before


def test_check_reports_a_nan_written_into_ecc_toml_by_hand(capsys, create_cli_project):
    project_dir = create_cli_project()
    with open(os.path.join(project_dir, "ecc.toml"), "a") as handle:
        handle.write("\n[params.floorplan]\ncore_util = nan\n")

    rc = cli_main.run(["check", "--project", project_dir, "--plain"])

    assert rc == 1
    assert "value nan is not a finite number for floorplan.core_util" in capsys.readouterr().out


def test_finite_values_are_still_accepted(capsys, create_cli_project):
    project_dir = create_cli_project()

    for key, raw in (
        ("floorplan.core_util", "0.5"),
        ("floorplan.macro_placer.macro_placement_halo", "2.5"),
        ("floorplan.core_margin", "2,3"),
    ):
        assert cli_main.run(["param", "set", key, raw, "--project", project_dir, "--plain"]) == 0
    capsys.readouterr()
