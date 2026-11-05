"""Execute the synthesis script on literal constants and imported tie cells."""

import json
import subprocess
from collections import Counter

import pytest

from chipcompiler.data import OriginDesign, Parameters, Workspace
from chipcompiler.data.pdk import get_pdk
from chipcompiler.tools.yosys import builder
from chipcompiler.tools.yosys.utility import get_yosys_runtime


@pytest.fixture
def yosys_runtime():
    command, env = get_yosys_runtime()
    if not command:
        pytest.skip("Yosys is not installed")
    return command, env


@pytest.fixture(params=["ics55", "sg13g2"])
def tie_pdk(request, tmp_path):
    pdk = get_pdk(request.param, pdk_root=tmp_path, validate=False)
    liberty = tmp_path / "cells.lib"
    liberty.write_text(
        f"""library(test) {{
  cell({pdk.tie_high_cell}) {{
    area : 1;
    pin({pdk.tie_high_port}) {{ direction : output; function : "1"; }}
  }}
  cell({pdk.tie_low_cell}) {{
    area : 1;
    pin({pdk.tie_low_port}) {{ direction : output; function : "0"; }}
  }}
  cell(BUF) {{
    area : 1;
    pin(A) {{ direction : input; }}
    pin(Y) {{ direction : output; function : "A"; }}
  }}
}}
"""
    )
    pdk.libs = [liberty]
    pdk.dont_use = []
    pdk.abc_driver_cell = "BUF"
    return pdk


def _synthesize(directory, source, pdk, yosys_runtime):
    workspace = Workspace(
        directory=directory,
        design=OriginDesign(name="top", top_module="top", origin_verilog=source),
        pdk=pdk,
        parameters=Parameters(data={"frequency_max": 100}),
    )
    step = builder.build_step(
        workspace,
        "Synthesis",
        input_def=None,
        input_verilog=source,
        output_verilog=directory / "top.v",
    )
    builder.build_step_space(step)
    builder.build_step_config(workspace, step)
    script_dir = step.script.dir
    assert script_dir is not None
    command, env = yosys_runtime
    result = subprocess.run(
        command + ["-Q", "-T", "-p", "tcl yosys_synthesis.tcl; write_json result.json"],
        cwd=script_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    module = json.loads((script_dir / "result.json").read_text())["modules"]["top"]
    return module, step.output.verilog


def _assert_tie_connections(module, pdk):
    polarities = {
        pdk.tie_high_cell: (pdk.tie_high_port, "1"),
        pdk.tie_low_cell: (pdk.tie_low_port, "0"),
    }
    drivers = {}
    loads = Counter()
    sinks = {}
    for name, cell in module["cells"].items():
        if cell["type"] in polarities:
            port, value = polarities[cell["type"]]
            (bit,) = cell["connections"][port]
            assert bit not in drivers, "multiple tie cells drive the same net"
            drivers[bit] = value
        else:
            sinks[name] = cell["connections"]
            for port, bits in cell["connections"].items():
                if cell["port_directions"][port] == "input":
                    loads.update(bits)
    for port in module["ports"].values():
        if port["direction"] == "output":
            loads.update(port["bits"])

    assert Counter(drivers.values()) == {"1": 5, "0": 6}
    assert {bit: loads[bit] for bit in drivers} == dict.fromkeys(drivers, 1)

    # Replace each driver by its constant to compare all original connections.
    def constants(bits):
        return [drivers.get(bit, bit) for bit in bits]

    observed = {
        name: {port: constants(bits) for port, bits in connections.items()}
        for name, connections in sinks.items()
    }
    assert observed == {
        "hi_sink": {
            "A": ["1", "1"],
            "B": ["1"],
            "C": module["ports"]["data"]["bits"],
            "Y": module["ports"]["hi_result"]["bits"],
        },
        "lo_sink": {
            "A": ["0", "0"],
            "B": ["0"],
            "C": module["ports"]["data"]["bits"],
            "Y": module["ports"]["lo_result"]["bits"],
        },
    }
    assert {
        name: constants(module["ports"][name]["bits"])
        for name in ("hi_ports_0", "hi_ports_1", "lo_ports_0", "lo_ports_1", "undefined_port")
    } == {
        "hi_ports_0": ["1"],
        "hi_ports_1": ["1"],
        "lo_ports_0": ["0"],
        "lo_ports_1": ["0"],
        "undefined_port": ["0"],
    }


@pytest.mark.parametrize("import_ties", [False, True], ids=["rtl", "mapped_netlist"])
def test_synthesis_tie_fanout_one(tmp_path, tie_pdk, yosys_runtime, import_ties):
    ties = (
        f"{tie_pdk.tie_high_cell} old_hi (.{tie_pdk.tie_high_port}(hi));\n"
        f"{tie_pdk.tie_low_cell} old_lo (.{tie_pdk.tie_low_port}(lo));"
        if import_ties
        else "assign hi = 1'b1; assign lo = 1'b0;"
    )
    source = tmp_path / "top.v"
    source.write_text(
        f"""(* blackbox *) module SINK(input [1:0] A, input B, C, output Y);
endmodule
module top(input data, output hi_result, lo_result,
           output [1:0] hi_ports, lo_ports, output undefined_port);
  wire hi, lo;
  {ties}
  SINK hi_sink (.A({{hi, hi}}), .B(hi), .C(data), .Y(hi_result));
  SINK lo_sink (.A({{lo, lo}}), .B(lo), .C(data), .Y(lo_result));
  assign hi_ports = {{hi, hi}};
  assign lo_ports = {{lo, lo}};
  assign undefined_port = 1'bx;
endmodule
"""
    )
    module, netlist = _synthesize(tmp_path / "first", source, tie_pdk, yosys_runtime)
    _assert_tie_connections(module, tie_pdk)

    # Re-import the written netlist with a blackbox macro declaration, as a real
    # netlist-input project would do via its macro library.
    macro = tmp_path / "sink.lib"
    macro.write_text(
        "library(macros) { cell(SINK) { area : 1; "
        "bus(A) { bus_type : pair; direction : input; } "
        "pin(B) { direction : input; } pin(C) { direction : input; } "
        "pin(Y) { direction : output; } } "
        "type(pair) { base_type : array; data_type : bit; bit_width : 2; "
        "bit_from : 1; bit_to : 0; downto : true; } }"
    )
    tie_pdk.libs.append(macro)
    repeated, _ = _synthesize(tmp_path / "second", netlist, tie_pdk, yosys_runtime)
    _assert_tie_connections(repeated, tie_pdk)
