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
    assert step.feature.step is not None
    step.feature.step.write_text(
        json.dumps(
            {
                "run": {
                    "state": "Success",
                    "runtime_seconds": 12.345,
                    "peak_memory_mb": 256.5,
                },
                "constraints": {
                    "sdc": {
                        "availability": "available",
                        "sha256": "a" * 64,
                        "size_bytes": 128,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assert step.feature.stat is not None
    step.feature.stat.write_text(
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
    assert step.analysis.metrics is not None
    assert step.analysis.metrics.name == "qor_metrics.json"
    assert step.analysis.metrics.is_file()
    assert step.analysis.qor_metrics is not None
    assert step.analysis.qor_metrics.is_file()
    assert step.analysis.qor_summary is not None
    assert step.analysis.qor_summary.is_file()
    assert step.analysis.qor_hotspots is not None
    assert step.analysis.qor_hotspots.is_file()
    assert step.analysis.dir is not None
    assert not (step.analysis.dir / "Synthesis_metrics.json").exists()

    qor_metrics = json.loads(step.analysis.qor_metrics.read_text(encoding="utf-8"))
    assert qor_metrics["schema_version"] == 3
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
    assert records["runtime_seconds"] == {
        "id": "runtime_seconds",
        "display_name": "Step Runtime",
        "value": 12.345,
        "unit": "s",
        "category": "runtime",
        "direction": "lower_is_better",
        "scope": "synthesis_execution",
        "corner": None,
        "project_role": "trend",
        "step_role": "secondary",
        "analysis_group": "runtime",
        "rating": {"gate": False, "score": False, "trend": True},
        "confidence": "high",
        "source": {
            "kind": "feature",
            "path": "feature/Synthesis.step.json",
            "selector": "/run/runtime_seconds",
        },
    }
    assert records["peak_memory_mb"]["value"] == 256.5
    assert qor_metrics["context"] == {
        "timing_constraints": {
            "sdc_sha256": "a" * 64,
            "sdc_size_bytes": 128,
            "source": {
                "kind": "feature",
                "path": "feature/Synthesis.step.json",
                "selector": "/constraints/sdc",
            },
        }
    }

    summary = json.loads(step.analysis.qor_summary.read_text(encoding="utf-8"))
    assert summary["schema_version"] == 4
    assert summary["analysis_status"] == "valid"
    assert summary["quality_status"] == "pass"
    assert summary["gates"] == []
    assert summary["missing_metrics"] == []
