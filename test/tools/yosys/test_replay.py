"""Replay export must preserve synthesis state, including traversal order."""

import json
import subprocess
from pathlib import Path

import pytest

from chipcompiler.tools.yosys import builder
from chipcompiler.tools.yosys.utility import get_yosys_runtime


@pytest.mark.parametrize("capture_error", [False, True])
def test_logical_capture_preserves_order_and_mapped_netlist(tmp_path, capture_error):
    command, env = get_yosys_runtime()
    if not command:
        pytest.skip("Yosys is not installed")
    env.pop("ECC_REPLAY_CAPTURE_DIR", None)
    source = tmp_path / "top.v"
    source.write_text(
        "module top(input [7:0] a,b,input c,output [7:0] y);\nassign y=c?(a-b):(a+b); endmodule\n"
    )
    helper = Path(builder.__file__).parent / "scripts" / "replay.tcl"
    outputs = []
    for enabled in (False, True):
        run = tmp_path / str(enabled)
        run.mkdir()
        capture = run / "capture"
        if capture_error and enabled:
            (capture / "logical" / "000000.json").mkdir(parents=True)
        script = run / "run.tcl"
        script.write_text(
            f"yosys -import\nsource {{{helper}}}\n"
            f"yosys read_verilog {{{source}}}\n"
            "yosys synth -top top -run :fine\n"
            + (f"set ::env(ECC_REPLAY_CAPTURE_DIR) {{{capture}}}\n" if enabled else "")
            + "replay_logical generic_synthesis\n"
            # A sorted design can still be logically equivalent while changing
            # later technology mapping. Assert iteration order before ABC too.
            "yosys tee -o order.txt select -list */c:*\n"
            "yosys abc -g AND,OR,XOR,XNOR,MUX\n"
            "yosys write_json final.json\n"
        )
        result = subprocess.run(
            command + ["-Q", "-T", "-c", str(script)],
            cwd=run,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        outputs.append(
            ((run / "order.txt").read_text(), json.loads((run / "final.json").read_text()))
        )
        if enabled:
            if capture_error:
                assert json.loads((capture / "error.json").read_text()) == {
                    "error": "logical capture failed"
                }
            else:
                snapshot = json.loads((capture / "logical" / "000000.json").read_text())
                assert snapshot["modules"]["top"]["cells"]
                assert (capture / "logical" / "000000.event").is_file()
        else:
            assert not capture.exists()
    assert outputs[0] == outputs[1]
