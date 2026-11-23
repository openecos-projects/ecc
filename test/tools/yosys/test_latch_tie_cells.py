"""Execute the synthesis script on a tiny latch and tri-state buffer Liberty."""

import json
import subprocess

import pytest

from chipcompiler.data import OriginDesign, Parameters, Workspace
from chipcompiler.data.pdk import PDK_ICS55
from chipcompiler.tools.yosys import builder
from chipcompiler.tools.yosys.utility import get_yosys_runtime


@pytest.fixture
def yosys_runtime():
    command, env = get_yosys_runtime()
    if not command:
        pytest.skip("Yosys is not installed")
    return command, env


def _write_latch_liberty(path, enable_pin="GN"):
    """A latch + tri-state buffer library; the latch enable pin name is variable."""
    path.write_text(
        f"""library(test) {{
  cell(LATN) {{
    area : 1;
    latch(IQ, IQN) {{
      enable : "{enable_pin}'";
      data_in : "D";
    }}
    pin(D) {{ direction : input; }}
    pin({enable_pin}) {{ direction : input; }}
    pin(Q) {{ direction : output; function : "IQ"; }}
  }}
  cell(TBUF) {{
    area : 1;
    pin(A) {{ direction : input; }}
    pin(OE) {{ direction : input; }}
    pin(Y) {{ direction : output; function : "A"; three_state : "!OE"; }}
  }}
}}
"""
    )
    return path


def _latch_pdk(tmp_path, enable_pin="GN", latch_pins=None):
    pdk = PDK_ICS55(pdk_root=tmp_path)
    pdk.libs = [_write_latch_liberty(tmp_path / "cells.lib", enable_pin)]
    pdk.dont_use = []
    pdk.tie_high_cell = ""
    pdk.tie_low_cell = ""
    pdk.abc_driver_cell = ""
    pdk.latch_cells = {"$_DLATCH_N_": "LATN"}
    pdk.latch_pins = {"data": "D"} if latch_pins is None else latch_pins
    pdk.inverter_cell = ""
    pdk.tbuf_cell = "TBUF"
    pdk.tbuf_pins = {"data": "A"}
    return pdk


@pytest.fixture
def latch_pdk(tmp_path):
    return _latch_pdk(tmp_path)


def _synthesize(directory, source, pdk, yosys_runtime):
    workspace = Workspace(
        directory=directory,
        design=OriginDesign(name="top", top_module="top", origin_verilog=source),
        pdk=pdk,
        parameters=Parameters(data={"frequency_max": 100}),
    )
    step = builder.build_step(
        workspace,
        "synthesis",
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
    return module, step


def test_synthesis_maps_negative_enable_latch_to_liberty_pins(tmp_path, latch_pdk, yosys_runtime):
    source = tmp_path / "top.v"
    source.write_text(
        """module top(input en, d, output q);
  always @* if (!en) q = d;
endmodule
"""
    )
    module, _step = _synthesize(tmp_path / "run", source, latch_pdk, yosys_runtime)

    latches = [cell for cell in module["cells"].values() if cell["type"] == "LATN"]
    assert len(latches) == 1
    (latch,) = latches
    assert set(latch["port_directions"]) == {"D", "GN", "Q"}
    assert latch["port_directions"]["D"] == "input"
    assert latch["port_directions"]["GN"] == "input"
    assert latch["port_directions"]["Q"] == "output"


def test_synthesis_writes_tristate_buffer_techmap_with_liberty_pins(
    tmp_path, latch_pdk, yosys_runtime
):
    # A tri-state mux inferred from RTL does not survive this script's early
    # optimization, so this checks the generated techmap source directly:
    # the $_TBUF_ replacement module must wire the real cell's Liberty-derived
    # pins (A/OE/Y here), not some other PDK's names.
    source = tmp_path / "top.v"
    source.write_text(
        """module top(input a, oe, output y);
  assign y = oe ? a : 1'bz;
endmodule
"""
    )
    _module, step = _synthesize(tmp_path / "run", source, latch_pdk, yosys_runtime)

    assert step.data.tmp is not None
    primitive_map = (step.data.tmp / "primitive_map.v").read_text(encoding="utf-8")
    assert r"module \$_TBUF_ (A, E, Y);" in primitive_map
    assert "TBUF _TECHMAP_REPLACE_ (.A(A), .OE(E), .Y(Y));" in primitive_map


def test_synthesis_follows_a_renamed_liberty_enable_pin(tmp_path, yosys_runtime):
    """The enable is whatever the Liberty calls it, not a name baked into the PDK."""
    source = tmp_path / "top.v"
    source.write_text(
        """module top(input en, d, output q);
  always @* if (!en) q = d;
endmodule
"""
    )
    pdk = _latch_pdk(tmp_path, enable_pin="ENABLE_B")
    module, _step = _synthesize(tmp_path / "run", source, pdk, yosys_runtime)

    (latch,) = [cell for cell in module["cells"].values() if cell["type"] == "LATN"]
    assert latch["port_directions"] == {"D": "input", "ENABLE_B": "input", "Q": "output"}


def test_synthesis_rejects_a_latch_master_whose_named_role_is_not_in_liberty(
    tmp_path, yosys_runtime
):
    source = tmp_path / "top.v"
    source.write_text(
        """module top(input en, d, output q);
  always @* if (!en) q = d;
endmodule
"""
    )
    pdk = _latch_pdk(tmp_path, latch_pins={"data": "DIN"})

    with pytest.raises(AssertionError, match="Liberty has no input pin DIN"):
        _synthesize(tmp_path / "run", source, pdk, yosys_runtime)


def test_synthesis_rejects_a_tristate_master_with_more_than_one_output(tmp_path, yosys_runtime):
    """Only a latch may resolve its output by the Q convention.

    A tri-state master declaring both a non-inverting Y and an inverting Q must
    not silently map the design output onto Q.
    """
    liberty = tmp_path / "two_output_tbuf.lib"
    liberty.write_text(
        """library(test) {
  cell(LATN) {
    area : 1;
    latch(IQ, IQN) {
      enable : "GN'";
      data_in : "D";
    }
    pin(D) { direction : input; }
    pin(GN) { direction : input; }
    pin(Q) { direction : output; function : "IQ"; }
  }
  cell(TBUF) {
    area : 1;
    pin(A) { direction : input; }
    pin(OE) { direction : input; }
    pin(Y) { direction : output; function : "A"; three_state : "!OE"; }
    pin(Q) { direction : output; function : "A'"; three_state : "!OE"; }
  }
}
"""
    )
    pdk = _latch_pdk(tmp_path)
    pdk.libs = [liberty]

    source = tmp_path / "top.v"
    source.write_text(
        """module top(input a, oe, output y);
  assign y = oe ? a : 1'bz;
endmodule
"""
    )
    with pytest.raises(AssertionError, match="expected exactly one output pin"):
        _synthesize(tmp_path / "run", source, pdk, yosys_runtime)
