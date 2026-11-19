import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.data.flow.document import FlowDocument
from chipcompiler.data.workspace import Flow
from chipcompiler.engine.step_outputs import resolve_workspace_step_outputs

_STEPS: list[dict[str, str]] = [
    {"name": "synthesis", "tool": "yosys", "state": "Success"},
    {"name": "pre_floorplan", "tool": "ecc", "state": "Success"},
    {"name": "macro_placement", "tool": "dreamplace", "state": "Unstart"},
    {"name": "post_floorplan", "tool": "ecc", "state": "Unstart"},
    {"name": "cts", "tool": "ecc", "state": "Unstart"},
    {"name": "timing_optimization", "tool": "sizer", "state": "Unstart"},
]


def _workspace(directory: Path, steps: list[dict[str, str]] = _STEPS) -> SimpleNamespace:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "home").mkdir(exist_ok=True)
    from test.flow_fixture import current_flow_document

    flow_data: FlowDocument = current_flow_document(steps)
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
        "synthesis",
        "pre_floorplan",
        "macro_placement",
        "post_floorplan",
        "cts",
        "timing_optimization",
    ]
    by_step = {entry["step"]: entry for entry in result["steps"]}
    assert by_step["synthesis"]["tool"] == "yosys"
    assert by_step["synthesis"]["verilog"]["path"].endswith(
        "synthesis_yosys/output/gcd_synthesis.v.gz"
    )
    assert by_step["pre_floorplan"]["def"]["path"].endswith(
        "pre_floorplan_ecc/output/gcd_pre_floorplan.def.gz"
    )
    assert by_step["macro_placement"]["def"]["path"].endswith(
        "macro_placement_dreamplace/output/gcd_macro_placement.def.gz"
    )
    assert by_step["cts"]["verilog"]["path"].endswith("cts_ecc/output/gcd_cts.v.gz")
    assert by_step["timing_optimization"]["def"]["path"].endswith(
        "timing_optimization_sizer/output/gcd_timing_optimization.def.gz"
    )
    assert by_step["pre_floorplan"]["state"] == "Success"
    assert by_step["cts"]["state"] == "Unstart"


def test_artifact_existence_reflects_the_filesystem(tmp_path):
    workspace = _workspace(tmp_path / "ws_0001")
    output = tmp_path / "ws_0001" / "pre_floorplan_ecc" / "output"
    output.mkdir(parents=True)
    (output / "gcd_pre_floorplan.def.gz").write_bytes(b"def")

    result = resolve_workspace_step_outputs(workspace)
    by_step = {entry["step"]: entry for entry in result["steps"]}

    assert by_step["pre_floorplan"]["def"]["exists"] is True
    assert by_step["pre_floorplan"]["verilog"]["exists"] is False
    assert by_step["synthesis"]["verilog"]["exists"] is False


def test_sdc_comes_from_the_loaded_workspace(tmp_path):
    workspace = _workspace(tmp_path / "ws_0001")
    sdc = tmp_path / "ws_0001" / "origin" / "gcd.sdc"
    sdc.parent.mkdir(parents=True)
    sdc.write_text("create_clock ...")

    result = resolve_workspace_step_outputs(workspace)

    assert result["sdc"] == {"path": "origin/gcd.sdc", "exists": True}


def test_step_filter_selects_one_entry(tmp_path):
    workspace = _workspace(tmp_path / "ws_0001")

    result = resolve_workspace_step_outputs(workspace, "post_floorplan")

    assert [entry["step"] for entry in result["steps"]] == ["post_floorplan"]


def test_unknown_step_raises(tmp_path):
    workspace = _workspace(tmp_path / "ws_0001")

    with pytest.raises(ValueError, match="flow step not found"):
        resolve_workspace_step_outputs(workspace, "floorplan")
