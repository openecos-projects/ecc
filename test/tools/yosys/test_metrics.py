import json

from chipcompiler.data import OriginDesign, StepEnum, Workspace
from chipcompiler.tools.yosys.builder import build_step, build_step_space
from chipcompiler.tools.yosys.metrics import build_step_metrics


def test_synthesis_metrics_write_v2_qor_files_without_legacy_metrics(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.SYNTHESIS.value,
        input_def=None,
        input_verilog=tmp_path / "gcd.v",
    )
    build_step_space(step)
    step.feature["stat"].write_text(
        json.dumps(
            {
                "design": {
                    "num_cells": 123,
                    "area": 456.789,
                    "num_wires": 87,
                    "num_port_bits": 10,
                }
            }
        ),
        encoding="utf-8",
    )

    metrics = build_step_metrics(workspace, step)

    assert metrics is not None
    assert step.analysis["metrics"].name == "qor_metrics.json"
    assert step.analysis["metrics"].is_file()
    assert step.analysis["qor_metrics"].is_file()
    assert step.analysis["qor_summary"].is_file()
    assert step.analysis["qor_hotspots"].is_file()
    assert not (step.analysis["dir"] / "Synthesis_metrics.json").exists()

    qor_metrics = json.loads(step.analysis["qor_metrics"].read_text(encoding="utf-8"))
    assert qor_metrics["schema_version"] == 2
    records = {record["id"]: record for record in qor_metrics["metrics"]}
    assert records["synthesis_cell_area"]["value"] == 456.79
    assert records["synthesis_cell_count"]["value"] == 123
    assert records["synthesis_wire_count"]["value"] == 87
    assert records["synthesis_port_count"]["value"] == 10
    assert records["synthesis_cell_area"]["source"] == {
        "kind": "feature",
        "path": "feature/Synthesis_stat.json",
        "selector": "/design/area",
    }

    summary = json.loads(step.analysis["qor_summary"].read_text(encoding="utf-8"))
    assert summary["status"] == "pass"
    assert summary["missing_metrics"] == []
