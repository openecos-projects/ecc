"""A workspace must not depend on the installation it was created from."""

from pathlib import Path

from chipcompiler.data import Parameters, Workspace
from chipcompiler.data.pdk import PDK
from chipcompiler.data.workspace import init_workspace_config, refresh_workspace_config
from chipcompiler.utility import json_read, json_write


def _pdk_root(tmp_path):
    root = tmp_path / "pdk"
    (root / "ecc-configs" / "ecc").mkdir(parents=True)
    return root


def test_filler_masters_from_the_pdk_root_survive_workspace_initialization(tmp_path):
    root = _pdk_root(tmp_path)
    assert json_write(
        root / "ecc-configs" / "ecc" / "filler_ecc.json",
        {"MJ": {"-filler": "FILL_CUSTOM"}},
    )
    workspace = Workspace(
        directory=tmp_path / "work",
        pdk=PDK(name="custom", root=root),
        parameters=Parameters(data={}),
    )

    init_workspace_config(workspace)

    assert json_read(workspace.config["filler"])["MJ"]["-filler"] == "FILL_CUSTOM"


def test_refresh_ignores_scenarios_the_installation_gained_since_creation(tmp_path):
    """An existing workspace's timing set is its own, not the installation's."""
    root = _pdk_root(tmp_path)
    override = root / "ecc-configs" / "ecc" / "sta_ecc.json"

    def policy(corner):
        return {
            "liberty": [{"corner": corner, "temperature": 25, "path": []}],
            "signoff": [{corner: ["TYPICAL"]}],
        }

    assert json_write(override, policy("TYP"))
    workspace = Workspace(
        directory=tmp_path / "work",
        pdk=PDK(name="custom", root=root),
        parameters=Parameters(data={"sdc": {"clock_list": "clk TYP:100"}}),
    )
    init_workspace_config(workspace)
    saved = workspace.config["sta"].read_bytes()

    assert json_write(override, policy("SLOW"))
    refresh_workspace_config(workspace)

    assert workspace.config["sta"].read_bytes() == saved
    generated = {
        path.name for path in Path(workspace.directory / "origin" / "pre_CTS").glob("*.tcl")
    }
    assert generated == {"TYP_25_TYPICAL.tcl"}
