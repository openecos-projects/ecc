#!/usr/bin/env python

import json
from pathlib import Path

from chipcompiler.data import create_workspace, load_workspace


def _create_minimal_ics55_pdk(root: Path) -> Path:
    tech_path = root / "prtech" / "techLEF" / "N551P6M.lef"
    tech_path.parent.mkdir(parents=True, exist_ok=True)
    tech_path.write_text("VERSION 5.8 ;\n")

    stdcell_root = root / "IP" / "STD_cell" / "ics55_LLSC_H7C_V1p10C100"
    for flavor in ("ics55_LLSC_H7CR", "ics55_LLSC_H7CL"):
        lef_path = stdcell_root / flavor / "lef" / f"{flavor}_ecos.lef"
        lef_path.parent.mkdir(parents=True, exist_ok=True)
        lef_path.write_text("VERSION 5.8 ;\n")

        lib_path = stdcell_root / flavor / "liberty" / f"{flavor}_ss_rcworst_1p08_125_nldm.lib"
        lib_path.parent.mkdir(parents=True, exist_ok=True)
        lib_path.write_text("library(test) { }\n")

    return root


def _default_parameters() -> dict:
    return {
        "PDK": "ics55",
        "Design": "gcd",
        "Top module": "gcd",
        "Clock": "clk",
        "Frequency max [MHz]": 100,
    }


def test_create_workspace_persists_pdk_root_in_parameters(tmp_path):
    pdk_root = _create_minimal_ics55_pdk(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    workspace = create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters=_default_parameters(),
        pdk_root=str(pdk_root),
    )

    assert workspace is not None
    resolved_root = str(pdk_root.resolve())
    assert workspace.pdk.root == resolved_root
    assert workspace.parameters.data.get("PDK Root") == resolved_root

    parameters_data = json.loads((workspace_dir / "home" / "parameters.json").read_text())
    assert parameters_data.get("PDK Root") == resolved_root


def test_load_workspace_restores_pdk_root_from_parameters(tmp_path):
    pdk_root = _create_minimal_ics55_pdk(tmp_path / "ics55")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="ics55",
        parameters=_default_parameters(),
        pdk_root=str(pdk_root),
    )

    loaded = load_workspace(str(workspace_dir))

    assert loaded is not None
    resolved_root = str(pdk_root.resolve())
    assert loaded.pdk.root == resolved_root
    assert loaded.parameters.data.get("PDK Root") == resolved_root
    assert all(path.startswith(resolved_root) for path in loaded.pdk.libs)


#SG13G2 workspace tests

def _create_minimal_sg13g2_pdk(root: Path) -> Path:
    """Create the minimal SG13G2 directory tree required by get_pdk()."""
    tech_path = root / "libs.ref" / "sg13g2_stdcell" / "lef" / "sg13g2_tech.lef"
    tech_path.parent.mkdir(parents=True, exist_ok=True)
    tech_path.write_text("VERSION 5.8 ;\n")

    lef_path = root / "libs.ref" / "sg13g2_stdcell" / "lef" / "sg13g2_stdcell.lef"
    lef_path.write_text("VERSION 5.8 ;\n")

    lib_path = root / "libs.ref" / "sg13g2_stdcell" / "lib" / "sg13g2_stdcell_typ_1p20V_25C.lib"
    lib_path.parent.mkdir(parents=True, exist_ok=True)
    lib_path.write_text("library(test) { }\n")

    return root


def _sg13g2_default_parameters() -> dict:
    return {
        "PDK": "sg13g2",
        "Design": "gcd",
        "Top module": "gcd",
        "Clock": "clk",
        "Frequency max [MHz]": 100,
    }


def test_create_workspace_sg13g2_persists_pdk_root_in_parameters(tmp_path):
    pdk_root = _create_minimal_sg13g2_pdk(tmp_path / "sg13g2")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    workspace = create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="sg13g2",
        parameters=_sg13g2_default_parameters(),
        pdk_root=str(pdk_root),
    )

    assert workspace is not None
    resolved_root = str(pdk_root.resolve())
    assert workspace.pdk.root == resolved_root
    assert workspace.parameters.data.get("PDK Root") == resolved_root

    parameters_data = json.loads((workspace_dir / "home" / "parameters.json").read_text())
    assert parameters_data.get("PDK Root") == resolved_root


def test_load_workspace_sg13g2_restores_pdk_root_from_parameters(tmp_path):
    pdk_root = _create_minimal_sg13g2_pdk(tmp_path / "sg13g2")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="sg13g2",
        parameters=_sg13g2_default_parameters(),
        pdk_root=str(pdk_root),
    )

    loaded = load_workspace(str(workspace_dir))

    assert loaded is not None
    resolved_root = str(pdk_root.resolve())
    assert loaded.pdk.root == resolved_root
    assert loaded.parameters.data.get("PDK Root") == resolved_root
    assert all(path.startswith(resolved_root) for path in loaded.pdk.libs)
