"""Compare-copy preparation of LEC netlists: physical cells, empty ports, supply pins."""

import gzip
from types import SimpleNamespace

import pytest

from chipcompiler.tools.kepler_formal.netlist_prep import (
    liberty_supply_pins,
    physical_cell_names,
    prepare_netlist,
)


def test_prepare_netlist_strips_physical_cells_and_decompresses(tmp_path):
    netlist = tmp_path / "lvs.v"
    netlist.write_text(
        "module gcd (clk);\n"
        "  input clk;\n"
        "  FILLTAPH7R BNDRY_CAP_1 (  );\n"
        "  FILLER4H7R FILLER4H7R_0 (  );\n"
        "  FILLER4H7R FILLER4H7R_1(.VDD(VDD));\n"
        "  FILLCAP16H7L DCAP_1 (  );\n"
        "  P65_1233_FILLER50 IOFIL_E_0 (  );\n"
        "  P65_1233_CORNER corner_ll (  );\n"
        "endmodule\n"
    )
    physical = physical_cell_names(
        SimpleNamespace(fillers=["FILLER4H7R"], tap_cell="FILLTAPH7R", end_cap=None)
    )
    target = tmp_path / "gate_compare.v"

    prepared = prepare_netlist(netlist, target, physical)

    assert prepared == target
    text = target.read_text()
    assert "FILL" not in text
    assert "module gcd" in text

    # A netlist without physical cells is passed through untouched.
    clean = tmp_path / "syn.v"
    clean.write_text("module gcd (clk);\n  input clk;\nendmodule\n")
    assert prepare_netlist(clean, tmp_path / "unused.v", physical) == clean

    # gzip inputs are decompressed into the compare copy.
    gz = tmp_path / "syn.v.gz"
    gz.write_bytes(gzip.compress(b"module gcd (clk);\n  input clk;\nendmodule\n"))
    prepared_gz = prepare_netlist(gz, tmp_path / "golden_compare.v", physical)
    assert prepared_gz == tmp_path / "golden_compare.v"
    assert "module gcd" in prepared_gz.read_text()


def test_prepare_netlist_strips_empty_port_connections(tmp_path):
    netlist = tmp_path / "golden.v"
    netlist.write_text(
        "module top;\n"
        "  PAD_VDD pad0 (.VSS(),\n"
        "    .VDD1(vdd));\n"
        "  PAD_VSS pad1 (.VSS1(vss),\n"
        "    .VDDIO());\n"
        "  PAD_VDD pad2 (.VSSIO(), .VDD(vdd));\n"
        "endmodule\n"
    )
    target = tmp_path / "golden_compare.v"

    prepared = prepare_netlist(netlist, target, set())

    assert prepared == target
    text = prepared.read_text()
    assert ".VSS()" not in text
    assert ".VDDIO()" not in text
    assert ".VSSIO()" not in text
    assert "PAD_VDD pad0 (.VDD1(vdd));" in text
    assert "PAD_VSS pad1 (.VSS1(vss));" in text
    assert "PAD_VDD pad2 (.VDD(vdd));" in text


def test_prepare_netlist_strips_standard_cell_supply_connections(tmp_path):
    liberty = tmp_path / "stdcell.lib"
    liberty.write_text(
        "library(test) {\n"
        "  cell (BUFX20H7L) {\n"
        "    pg_pin (VDD) { pg_type : primary_power; }\n"
        "    pg_pin (VSS) { pg_type : primary_ground; }\n"
        "  }\n"
        "}\n"
    )
    netlist = tmp_path / "gate.v"
    netlist.write_text(
        "module top;\n"
        "  BUFX20H7L u0 (.A(a), .VDD(VDD), .VSS(VSS), .Y(y));\n"
        "  P65_1233_VDD1 pad0 (.VDD1(PLL_AVDD));\n"
        "  P65_1233_VDD3 pad1 (.VDD(PLL_DVDD));\n"
        "endmodule\n"
    )
    target = tmp_path / "gate_compare.v"

    prepared = prepare_netlist(netlist, target, set(), liberty_supply_pins([liberty]))

    assert prepared == target
    text = prepared.read_text()
    assert "BUFX20H7L u0 (.A(a), .Y(y));" in text
    assert ".VDD1(PLL_AVDD)" in text
    assert ".VDD(PLL_DVDD)" in text


def test_prepare_netlist_strips_supply_connections_without_instance_whitespace(tmp_path):
    liberty = tmp_path / "stdcell.lib"
    liberty.write_text(
        "library(test) {\n"
        "  cell (BUFX20H7L) {\n"
        "    pg_pin (VDD) { pg_type : primary_power; }\n"
        "    pg_pin (VSS) { pg_type : primary_ground; }\n"
        "  }\n"
        "}\n"
    )
    netlist = tmp_path / "gate.v"
    netlist.write_text(
        "module top;\n"
        "  BUFX20H7L u0 (.A(a), .VDD(VDD), .VSS(VSS), .Y(y));\n"
        "  BUFX20H7L u1(.A(a),.VDD(VDD),.VSS(VSS),.Y(y));\n"
        "  BUFX20H7L \\u2 (.A(a), .VDD(VDD), .Y(y));\n"
        "endmodule\n"
    )
    target = tmp_path / "gate_compare.v"

    prepared = prepare_netlist(netlist, target, set(), liberty_supply_pins([liberty]))

    assert prepared == target
    text = prepared.read_text()
    assert "BUFX20H7L u0 (.A(a), .Y(y));" in text
    assert "BUFX20H7L u1(.A(a),.Y(y));" in text
    assert "BUFX20H7L \\u2 (.A(a), .Y(y));" in text
    assert ".VDD(VDD)" not in text
    assert ".VSS(VSS)" not in text


def test_prepare_netlist_strips_final_supply_connection_from_spare_cell(tmp_path):
    liberty = tmp_path / "stdcell.lib"
    liberty.write_text(
        "library(test) {\n"
        "  cell (BUF) {\n"
        "    pg_pin (VDD) { pg_type : primary_power; }\n"
        "    pg_pin (VSS) { pg_type : primary_ground; }\n"
        "  }\n"
        "}\n"
    )
    netlist = tmp_path / "gate.v"
    netlist.write_text(
        "module top;\n"
        "  BUF spare (.A(), .Y(), .VDD(VDD), .VSS(VSS));\n"
        "  BUF compact(.A(),.Y(),.VDD(VDD),.VSS(VSS));\n"
        "endmodule\n"
    )
    target = tmp_path / "gate_compare.v"

    prepared = prepare_netlist(netlist, target, set(), liberty_supply_pins([liberty]))

    assert prepared == target
    text = prepared.read_text()
    assert "BUF spare ();" in text
    assert "BUF compact();" in text
    assert ".VDD(VDD)" not in text
    assert ".VSS(VSS)" not in text


def test_prepare_netlist_preserves_functional_supply_named_ports(tmp_path):
    netlist = tmp_path / "golden.v"
    netlist.write_text(
        "module leaf(input VDD, output Y); assign Y = VDD; endmodule\n"
        "module top(input VDD, output Y); leaf u0 (.VDD(VDD), .Y(Y)); endmodule\n"
    )
    target = tmp_path / "golden_compare.v"

    prepared = prepare_netlist(netlist, target, set(), {"BUFX20H7L": {"VDD", "VSS"}})

    assert prepared == netlist
    assert ".VDD(VDD)" in netlist.read_text()


def test_prepare_netlist_filters_lef_physical_classes_without_name_assumptions(tmp_path):
    physical = {
        "PCORNER": "ENDCAP BOTTOMLEFT",
        "PFILL10": "PAD SPACER",
        "PFILL0001": "PAD SPACER",
        "well_contact": "CORE WELLTAP",
        "core_gap": "CORE SPACER",
        "edge_cap": "ENDCAP TOPRIGHT",
        "diode": "CORE ANTENNACELL",
    }
    functional = {
        "PCORNER_LOGIC": "CORE",
        "PFILL10_BUF": "CORE",
        "signal_pad": "PAD INPUT",
        "power_pad": "PAD POWER",
        "tie_high": "CORE TIEHIGH",
        "tie_low": "CORE TIELOW",
        "memory": "BLOCK",
        "pll": "BLOCK",
    }
    lef = tmp_path / "cells.lef"
    lef.write_text(
        "# MACRO commented_out CLASS CORE SPACER ; END commented_out\n"
        + "".join(
            f"MACRO {name}\n"
            f"  CLASS {cell_class} ;\n"
            '  PROPERTY note "CLASS CORE SPACER ;" ;\n'
            "  PIN VDD\n    USE POWER ;\n    PORT\n"
            "      CLASS CORE ;\n    END\n  END VDD\n"
            f"END {name}\n"
            for name, cell_class in (physical | functional).items()
        )
    )
    pdk = SimpleNamespace(lefs=[lef], fillers=[], tap_cell="", end_cap="")
    names = physical_cell_names(pdk)
    assert names == set(physical)

    retained = "".join(f"  {name} u_{name} (.A(a), .Y(y));\n" for name in functional)
    # Check multiple lines and an escaped instance name as well as empty cells.
    removed = "".join(f"  {name} u_{name} ();\n" for name in physical)
    original = (
        "module top(input a, output y);\n"
        + retained
        + removed
        + "  PFILL10 \\ring/fill[0] (\n    .VDD(VDD)\n  );\n"
        + "endmodule\n"
    )
    source = tmp_path / "routed.v"
    source.write_text(original)
    target = tmp_path / "gate_compare.v"

    assert prepare_netlist(source, target, names) == target
    assert [line for line in target.read_text().splitlines() if line.strip()] == (
        "module top(input a, output y);\n" + retained + "endmodule\n"
    ).splitlines()
    assert source.read_text() == original


def test_physical_cell_names_requires_configured_lef_to_exist(tmp_path):
    pdk = SimpleNamespace(lefs=[tmp_path / "missing.lef"])

    with pytest.raises(FileNotFoundError):
        physical_cell_names(pdk)
