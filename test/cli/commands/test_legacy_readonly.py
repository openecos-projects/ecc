import json
import os
from pathlib import Path

import pytest

from chipcompiler.cli import main as cli_main


def _create_legacy_workspace(project_dir, pdk_root):
    """A runs/default workspace downgraded to the legacy JSON config shape."""
    from chipcompiler.data import create_workspace

    rtl_path = os.path.join(project_dir, "rtl", "gcd.v")
    os.makedirs(os.path.dirname(rtl_path), exist_ok=True)
    with open(rtl_path, "w") as f:
        f.write("module gcd(input clk, output y); assign y = clk; endmodule\n")

    run_dir = os.path.join(project_dir, "runs", "default")
    workspace = create_workspace(
        directory=run_dir,
        origin_def="",
        origin_verilog=rtl_path,
        pdk="ics55",
        parameters={"pdk": "ics55", "design": "gcd", "top_module": "gcd", "clock": "clk"},
        pdk_root=str(pdk_root),
    )
    assert workspace is not None

    # Downgrade: long-key parameters.json replaces the TOML config, and
    # home.json's parameters pointer goes back to the legacy JSON file.
    home = os.path.join(run_dir, "home")
    legacy = {
        "PDK": "ics55",
        "Design": "gcd",
        "Top module": "gcd",
        "Clock": "clk",
        "Frequency max [MHz]": 250,
    }
    os.unlink(os.path.join(home, "ecc.toml"))
    with open(os.path.join(home, "parameters.json"), "w") as f:
        json.dump(legacy, f)
    home_json_path = os.path.join(home, "home.json")
    with open(home_json_path) as f:
        home_data = json.load(f)
    home_data["parameters"] = os.path.join(home, "parameters.json")
    with open(home_json_path, "w") as f:
        json.dump(home_data, f)
    return run_dir


@pytest.mark.parametrize(
    "command",
    [
        ["status"],
        ["log"],
        ["check"],
        ["config", "--resolved"],
    ],
)
def test_readonly_commands_never_migrate_legacy_workspace(
    command, tmp_path, capsys, create_cli_project, minimal_ics55_pdk_factory, create_flow_json
):
    """status/log/check/config on a legacy workspace rewrite nothing: they
    never call load_workspace, so no ecc.toml appears, the legacy JSON is
    not deleted, and home.json keeps its legacy pointer byte-identical."""
    pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
    project_dir = create_cli_project(pdk_root=pdk_root)
    run_dir = _create_legacy_workspace(project_dir, pdk_root)
    create_flow_json(run_dir, profile="main")

    home = os.path.join(run_dir, "home")
    watched = [os.path.join(home, name) for name in ("parameters.json", "home.json")]
    snapshots = {path: Path(path).read_bytes() for path in watched}
    ecc_toml = os.path.join(home, "ecc.toml")
    assert not os.path.exists(ecc_toml)

    rc = cli_main.run([*command, "--project", project_dir, "--json"])

    assert rc == 0
    assert {path: Path(path).read_bytes() for path in watched} == snapshots
    assert not os.path.exists(ecc_toml)
