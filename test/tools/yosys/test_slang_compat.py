"""Verify ``yosys_synthesis.tcl`` enables VCS compatibility for ``read_slang``."""

import io
import subprocess

import pytest

from chipcompiler.data import OriginDesign, Parameters, Workspace
from chipcompiler.data.pdk import PDK_ICS55
from chipcompiler.tools.yosys import builder
from chipcompiler.tools.yosys.utility import check_slang_support, get_yosys_runtime


@pytest.fixture
def yosys_slang_runtime(tmp_path):
    command, env = get_yosys_runtime()
    if not command:
        pytest.skip("Yosys is not installed")
    log = io.StringIO()
    if not check_slang_support(command, str(tmp_path), env, log):
        pytest.skip("Yosys slang frontend is not available")
    return command, env


def _nldm_timing(related_pin: str, sense: str) -> str:
    table = 'index_1 ("0.01, 0.1"); index_2 ("0.001, 0.01"); values("0.02, 0.04", "0.03, 0.05");'
    return (
        f'timing() {{ related_pin : "{related_pin}"; timing_sense : {sense}; '
        f"cell_rise(t2x2) {{ {table} }} rise_transition(t2x2) {{ {table} }} "
        f"cell_fall(t2x2) {{ {table} }} fall_transition(t2x2) {{ {table} }} }}"
    )


def _minimal_pdk(tmp_path):
    liberty = tmp_path / "cells.lib"
    liberty.write_text(
        f"""library(test) {{
  delay_model : table_lookup;
  time_unit : "1ns";
  capacitive_load_unit (1, pf);
  default_fanout_load : 1;
  lu_table_template(t2x2) {{
    variable_1 : input_net_transition;
    variable_2 : total_output_net_capacitance;
    index_1 ("0.01, 0.1");
    index_2 ("0.001, 0.01");
  }}
  cell(INV) {{
    area : 1;
    pin(A) {{ direction : input; capacitance : 0.002; }}
    pin(Y) {{ direction : output; function : "!A"; {_nldm_timing("A", "negative_unate")} }}
  }}
  cell(BUF) {{
    area : 1;
    pin(A) {{ direction : input; capacitance : 0.002; }}
    pin(Y) {{ direction : output; function : "A"; {_nldm_timing("A", "positive_unate")} }}
  }}
  cell(NAND2) {{
    area : 2;
    pin(A) {{ direction : input; capacitance : 0.002; }}
    pin(B) {{ direction : input; capacitance : 0.002; }}
    pin(Y) {{
      direction : output;
      function : "!(A * B)";
      {_nldm_timing("A", "negative_unate")}
      {_nldm_timing("B", "negative_unate")}
    }}
  }}
  cell(NOR2) {{
    area : 2;
    pin(A) {{ direction : input; capacitance : 0.002; }}
    pin(B) {{ direction : input; capacitance : 0.002; }}
    pin(Y) {{
      direction : output;
      function : "!(A + B)";
      {_nldm_timing("A", "negative_unate")}
      {_nldm_timing("B", "negative_unate")}
    }}
  }}
}}
""",
        encoding="utf-8",
    )
    pdk = PDK_ICS55(pdk_root=tmp_path)
    pdk.libs = [liberty]
    pdk.dont_use = []
    pdk.tie_high_cell = ""
    pdk.tie_low_cell = ""
    pdk.abc_driver_cell = "BUF"
    pdk.latch_cells = {}
    pdk.inverter_cell = ""
    pdk.tbuf_cell = ""
    return pdk


def test_synthesis_uses_compat_vcs_for_systemverilog_net_initializers(
    tmp_path, yosys_slang_runtime
):
    source = tmp_path / "top.sv"
    # Net-state initializers fail strict IEEE 1800 / deprecated --compat-mode
    # ("reading net state during design initialization unsupported"), e.g. Ibex.
    source.write_text(
        """module top (
  input  logic a_i,
  output logic y_o
);
  logic unused_a = a_i;
  assign y_o = ~a_i;
endmodule
""",
        encoding="utf-8",
    )
    run_dir = tmp_path / "run"
    workspace = Workspace(
        directory=run_dir,
        design=OriginDesign(name="top", top_module="top", origin_verilog=source),
        pdk=_minimal_pdk(tmp_path),
        parameters=Parameters(data={"frequency_max": 100}),
    )
    step = builder.build_step(
        workspace,
        "synthesis",
        input_def=None,
        input_verilog=source,
        output_verilog=run_dir / "top.v",
    )
    builder.build_step_space(step)
    builder.build_step_config(workspace, step)
    script_dir = step.script.dir
    assert script_dir is not None

    command, env = yosys_slang_runtime
    result = subprocess.run(
        command + ["-Q", "-T", "-p", "tcl yosys_synthesis.tcl"],
        cwd=script_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    combined = result.stdout + result.stderr

    assert result.returncode == 0, combined
    assert "--compat-mode" not in combined
    assert "Build succeeded: 0 errors, 0 warnings" in combined
    assert (run_dir / "top.v").is_file()
