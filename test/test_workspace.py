#!/usr/bin/env python

import json
from pathlib import Path

from chipcompiler.data import create_workspace, load_workspace


def _create_minimal_ics55_pdk(root: Path) -> Path:
    tech_path = root / "prtech" / "techLEF" / "N551P6M_ecos.lef"
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


# GF180MCU workspace tests

def _create_minimal_gf180mcu_pdk(root: Path) -> Path:
    """Create the minimal GF180MCU directory tree required by get_pdk()."""
    tech_path = root / "lef" / "gf180mcu_7t_tech.lef"
    tech_path.parent.mkdir(parents=True, exist_ok=True)
    tech_path.write_text("VERSION 5.8 ;\n")

    lef_path = root / "lef" / "gf180mcu_fd_sc_mcu7t5v0.lef"
    lef_path.write_text("VERSION 5.8 ;\n")

    lib_path = root / "lib" / "gf180mcu_fd_sc_mcu7t5v0__ss_125C_1p65V.lib"
    lib_path.parent.mkdir(parents=True, exist_ok=True)
    lib_path.write_text("library(test) { }\n")

    return root


def _gf180mcu_default_parameters() -> dict:
    return {
        "PDK": "gf180mcu",
        "Design": "gcd",
        "Top module": "gcd",
        "Clock": "clk",
        "Frequency max [MHz]": 50,
    }


def test_create_workspace_gf180mcu_persists_pdk_root_in_parameters(tmp_path):
    pdk_root = _create_minimal_gf180mcu_pdk(tmp_path / "gf180mcu")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    workspace = create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="gf180mcu",
        parameters=_gf180mcu_default_parameters(),
        pdk_root=str(pdk_root),
    )

    assert workspace is not None
    resolved_root = str(pdk_root.resolve())
    assert workspace.pdk.root == resolved_root
    assert workspace.parameters.data.get("PDK Root") == resolved_root

    parameters_data = json.loads((workspace_dir / "home" / "parameters.json").read_text())
    assert parameters_data.get("PDK Root") == resolved_root


def test_load_workspace_gf180mcu_restores_pdk_root_from_parameters(tmp_path):
    pdk_root = _create_minimal_gf180mcu_pdk(tmp_path / "gf180mcu")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="gf180mcu",
        parameters=_gf180mcu_default_parameters(),
        pdk_root=str(pdk_root),
    )

    loaded = load_workspace(str(workspace_dir))

    assert loaded is not None
    resolved_root = str(pdk_root.resolve())
    assert loaded.pdk.root == resolved_root
    assert loaded.parameters.data.get("PDK Root") == resolved_root
    assert all(path.startswith(resolved_root) for path in loaded.pdk.libs)


# SKY130 workspace tests

def _create_minimal_sky130_pdk(root: Path) -> Path:
    """Create the minimal SKY130 directory tree required by get_pdk()."""
    tech_path = root / "lef" / "sky130_fd_sc_hd.tech.lef"
    tech_path.parent.mkdir(parents=True, exist_ok=True)
    tech_path.write_text("VERSION 5.8 ;\n")

    lef_path = root / "lef" / "sky130_fd_sc_hd.lef"
    lef_path.write_text("VERSION 5.8 ;\n")

    lib_path = root / "lib" / "sky130_fd_sc_hd__tt_025C_1v80.lib"
    lib_path.parent.mkdir(parents=True, exist_ok=True)
    lib_path.write_text("library(test) { }\n")

    return root


def _sky130_default_parameters() -> dict:
    return {
        "PDK": "sky130",
        "Design": "gcd",
        "Top module": "gcd",
        "Clock": "clk",
        "Frequency max [MHz]": 100,
    }


def test_create_workspace_sky130_persists_pdk_root_in_parameters(tmp_path):
    pdk_root = _create_minimal_sky130_pdk(tmp_path / "sky130")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    workspace = create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="sky130",
        parameters=_sky130_default_parameters(),
        pdk_root=str(pdk_root),
    )

    assert workspace is not None
    resolved_root = str(pdk_root.resolve())
    assert workspace.pdk.root == resolved_root
    assert workspace.parameters.data.get("PDK Root") == resolved_root

    parameters_data = json.loads((workspace_dir / "home" / "parameters.json").read_text())
    assert parameters_data.get("PDK Root") == resolved_root


def test_load_workspace_sky130_restores_pdk_root_from_parameters(tmp_path):
    pdk_root = _create_minimal_sky130_pdk(tmp_path / "sky130")
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")

    workspace_dir = tmp_path / "workspace"
    create_workspace(
        directory=str(workspace_dir),
        origin_def="",
        origin_verilog=str(rtl_path),
        pdk="sky130",
        parameters=_sky130_default_parameters(),
        pdk_root=str(pdk_root),
    )

    loaded = load_workspace(str(workspace_dir))

    assert loaded is not None
    resolved_root = str(pdk_root.resolve())
    assert loaded.pdk.root == resolved_root
    assert loaded.parameters.data.get("PDK Root") == resolved_root
    assert all(path.startswith(resolved_root) for path in loaded.pdk.libs)
