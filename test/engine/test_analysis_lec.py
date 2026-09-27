"""Workspace-analysis LEC surfacing across engines.

lecResult is emitted for any ledger tool in LEC_STEP_TOOLS, with the step
directory resolved through the ledger's (name, tool) record — never the
name-keyed directory table.
"""

import json
from types import SimpleNamespace

from chipcompiler.engine.analysis import build_workspace_analysis
from chipcompiler.utility import file_digest


def _lec_workspace(tmp_path, tool, result_name):
    design = "gcd"
    golden = tmp_path / "golden.v"
    golden.write_text("module gcd; endmodule\n")
    gate = tmp_path / "gate.v"
    gate.write_text("module gcd; endmodule\n")
    golden_sha, golden_size = file_digest(golden)
    gate_sha, gate_size = file_digest(gate)

    step_dir = tmp_path / result_name
    output = step_dir / "output"
    output.mkdir(parents=True)
    payload = {
        "status": "proven",
        "golden_verilog": str(golden),
        "gate_verilog": str(gate),
        "golden_sha256": golden_sha,
        "golden_size_bytes": golden_size,
        "gate_sha256": gate_sha,
        "gate_size_bytes": gate_size,
    }
    (output / f"{design}_lec_result.json").write_text(json.dumps(payload))

    workspace = SimpleNamespace(
        directory=tmp_path,
        flow=SimpleNamespace(data={"steps": [{"name": "lec", "tool": tool, "state": "Success"}]}),
        design=SimpleNamespace(name=design),
    )
    return workspace


def test_analysis_emits_lec_result_for_a_kepler_formal_ledger(tmp_path):
    workspace = _lec_workspace(tmp_path, "kepler_formal", "lec_kepler_formal")

    analysis, artifacts = build_workspace_analysis(workspace, "ws-1")

    step = analysis["steps"][0]
    assert step["lecResult"]["status"] == "available"
    assert step["lecResult"]["data"]["status"] == "proven"
    assert step["lecResult"]["data"]["freshness_status"] == "proven"


def test_analysis_emits_lec_result_for_a_yosys_lec_ledger(tmp_path):
    workspace = _lec_workspace(tmp_path, "yosys_lec", "lec_yosys_lec")

    analysis, artifacts = build_workspace_analysis(workspace, "ws-1")

    step = analysis["steps"][0]
    assert step["lecResult"]["status"] == "available"
    assert step["lecResult"]["data"]["freshness_status"] == "proven"


def test_analysis_resolves_a_dual_ledger_through_the_tool_aware_mapping(tmp_path):
    # A raw name-keyed directory lookup would resolve lec_kepler_formal;
    # the dual-recorded ledger must resolve lec_dual/.
    workspace = _lec_workspace(tmp_path, "lec_dual", "lec_dual")

    analysis, artifacts = build_workspace_analysis(workspace, "ws-1")

    step = analysis["steps"][0]
    assert step["lecResult"]["status"] == "available"
    assert step["lecResult"]["data"]["freshness_status"] == "proven"
    lec_artifact = next(a for a in artifacts if a["kind"] == "lec_result")
    assert lec_artifact["reference"] == "lec_dual/output/gcd_lec_result.json"
