import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.data.workspace import Flow
from chipcompiler.engine.step_outputs import resolve_workspace_step_outputs

_STEPS = [
    {"name": "Synthesis", "tool": "yosys", "state": "Success"},
    {"name": "preFloorplan", "tool": "ecc", "state": "Success"},
    {"name": "macroPlacement", "tool": "dreamplace", "state": "Unstart"},
    {"name": "postFloorplan", "tool": "ecc", "state": "Unstart"},
    {"name": "CTS", "tool": "ecc", "state": "Unstart"},
    {"name": "Timing optimization", "tool": "sizer", "state": "Unstart"},
]


def _workspace(directory: Path, steps=_STEPS) -> SimpleNamespace:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "home").mkdir(exist_ok=True)
    flow_data = {"steps": steps}
    flow_path = directory / "home" / "flow.json"
    flow_path.write_text(json.dumps(flow_data))
    return SimpleNamespace(
        directory=directory.resolve(),
        design=SimpleNamespace(name="gcd", origin_def="", origin_verilog=""),
        pdk=SimpleNamespace(sdc=directory / "origin" / "gcd.sdc"),
        flow=Flow(path=flow_path, data=flow_data),
    )


def test_resolves_every_committed_step_with_builder_owned_paths(tmp_path):
    workspace = _workspace(tmp_path / "ws_0001")

    result = resolve_workspace_step_outputs(workspace)

    assert result["design"] == "gcd"
    assert result["directory"] == "."
    assert [entry["step"] for entry in result["steps"]] == [
        "Synthesis",
        "preFloorplan",
        "macroPlacement",
        "postFloorplan",
        "CTS",
        "Timing optimization",
    ]
    by_step = {entry["step"]: entry for entry in result["steps"]}
    assert by_step["Synthesis"]["tool"] == "yosys"
    assert by_step["Synthesis"]["verilog"]["path"].endswith(
        "Synthesis_yosys/output/gcd_Synthesis.v.gz"
    )
    assert by_step["preFloorplan"]["def"]["path"].endswith(
        "preFloorplan_ecc/output/gcd_preFloorplan.def.gz"
    )
    assert by_step["macroPlacement"]["def"]["path"].endswith(
        "macroPlacement_dreamplace/output/gcd_macroPlacement.def.gz"
    )
    assert by_step["CTS"]["verilog"]["path"].endswith("CTS_ecc/output/gcd_CTS.v.gz")
    assert by_step["Timing optimization"]["def"]["path"].endswith(
        "timing_optimization_sizer/output/gcd_timing_optimization.def.gz"
    )
    assert by_step["preFloorplan"]["state"] == "Success"
    assert by_step["CTS"]["state"] == "Unstart"


def test_artifact_existence_reflects_the_filesystem(tmp_path):
    workspace = _workspace(tmp_path / "ws_0001")
    output = tmp_path / "ws_0001" / "preFloorplan_ecc" / "output"
    output.mkdir(parents=True)
    (output / "gcd_preFloorplan.def.gz").write_bytes(b"def")

    result = resolve_workspace_step_outputs(workspace)
    by_step = {entry["step"]: entry for entry in result["steps"]}

    assert by_step["preFloorplan"]["def"]["exists"] is True
    assert by_step["preFloorplan"]["verilog"]["exists"] is False
    assert by_step["Synthesis"]["verilog"]["exists"] is False


def test_sdc_comes_from_the_loaded_workspace(tmp_path):
    workspace = _workspace(tmp_path / "ws_0001")
    sdc = tmp_path / "ws_0001" / "origin" / "gcd.sdc"
    sdc.parent.mkdir(parents=True)
    sdc.write_text("create_clock ...")

    result = resolve_workspace_step_outputs(workspace)

    assert result["sdc"] == {"path": "origin/gcd.sdc", "exists": True}


def test_step_filter_selects_one_entry(tmp_path):
    workspace = _workspace(tmp_path / "ws_0001")

    result = resolve_workspace_step_outputs(workspace, "postFloorplan")

    assert [entry["step"] for entry in result["steps"]] == ["postFloorplan"]


def test_unknown_step_raises(tmp_path):
    workspace = _workspace(tmp_path / "ws_0001")

    with pytest.raises(ValueError, match="flow step not found"):
        resolve_workspace_step_outputs(workspace, "Floorplan")
