from pathlib import Path

import pytest


def create_minimal_ics55_pdk(root: Path) -> Path:
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


def create_minimal_sg13g2_pdk(root: Path) -> Path:
    tech_path = root / "libs.ref" / "sg13g2_stdcell" / "lef" / "sg13g2_tech.lef"
    tech_path.parent.mkdir(parents=True, exist_ok=True)
    tech_path.write_text("VERSION 5.8 ;\n")

    lef_path = root / "libs.ref" / "sg13g2_stdcell" / "lef" / "sg13g2_stdcell.lef"
    lef_path.write_text("VERSION 5.8 ;\n")

    lib_path = root / "libs.ref" / "sg13g2_stdcell" / "lib" / "sg13g2_stdcell_typ_1p20V_25C.lib"
    lib_path.parent.mkdir(parents=True, exist_ok=True)
    lib_path.write_text("library(test) { }\n")

    return root


def ics55_parameters() -> dict:
    return {
        "PDK": "ics55",
        "Design": "gcd",
        "Top module": "gcd",
        "Clock": "clk",
        "Frequency max [MHz]": 100,
    }


def sg13g2_parameters() -> dict:
    return {
        "PDK": "sg13g2",
        "Design": "gcd",
        "Top module": "gcd",
        "Clock": "clk",
        "Frequency max [MHz]": 100,
    }


@pytest.fixture
def minimal_ics55_pdk_factory():
    return create_minimal_ics55_pdk


@pytest.fixture
def minimal_sg13g2_pdk_factory():
    return create_minimal_sg13g2_pdk


@pytest.fixture
def default_ics55_parameters():
    return ics55_parameters()


@pytest.fixture
def default_sg13g2_parameters():
    return sg13g2_parameters()


@pytest.fixture
def gcd_rtl_file(tmp_path):
    rtl_path = tmp_path / "gcd.v"
    rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
    return rtl_path
