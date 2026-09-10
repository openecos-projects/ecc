import json

from chipcompiler.data import OriginDesign, StepEnum, Workspace
from chipcompiler.tools.ecc.builder import build_step, build_step_space
from chipcompiler.tools.ecc.metrics import build_metrics_floorplan, build_metrics_lvs
from chipcompiler.tools.ecc.qor_detail_facts import database_fact_summary


def test_database_fact_summary_extracts_layout_and_instance_classes(tmp_path):
    path = tmp_path / "Floorplan.db.json"
    path.write_text(
        json.dumps(
            {
                "Design Layout": {
                    "die_area": 2259.861,
                    "core_area": 1778.432,
                    "die_bounding_width": 47.538,
                    "die_bounding_height": 47.538,
                    "die_usage": 0.34,
                    "core_usage": 0.42,
                },
                "Design Statis": {
                    "num_iopins": 58,
                    "num_instances": 615,
                    "num_nets": 361,
                },
                "Instances": {
                    "total": {"area": 1200.0, "num": 615},
                    "clock": {"area": 20.0, "num": 10},
                    "iopads": {"area": 10.0, "num": 2},
                    "logic": {"area": 709.25, "num": 286},
                    "macros": {"area": 401.5, "num": 3},
                },
            }
        ),
        encoding="utf-8",
    )

    summary = database_fact_summary(path)

    assert summary is not None
    assert summary["layout"]["core_area"] == 1778.432
    assert summary["instance_total"]["count"] == 615
    assert {item["kind"] for item in summary["instance_classes"]} == {
        "clock",
        "iopads",
        "logic",
        "macros",
    }


def test_floorplan_qor_metrics_include_instance_classes_and_database_facts(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.FLOORPLAN.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    assert step.feature.db is not None
    step.feature.db.write_text(
        json.dumps(
            {
                "Design Layout": {
                    "die_area": 2259.861,
                    "core_area": 1778.432,
                    "die_bounding_width": 47.538,
                    "die_bounding_height": 47.538,
                    "die_usage": 0.34,
                    "core_usage": 0.42,
                },
                "Design Statis": {
                    "num_iopins": 58,
                    "num_instances": 615,
                    "num_nets": 361,
                },
                "Instances": {
                    "total": {"area": 1200.0, "num": 615},
                    "clock": {"area": 20.0, "num": 10},
                    "iopads": {"area": 10.0, "num": 2},
                    "logic": {"area": 709.25, "num": 286},
                    "macros": {"area": 401.5, "num": 3},
                },
            }
        ),
        encoding="utf-8",
    )

    metrics = build_metrics_floorplan(workspace, step)

    assert metrics is not None
    assert step.analysis.qor_metrics is not None
    assert step.analysis.qor_metrics.exists()
    qor_metrics = json.loads(step.analysis.qor_metrics.read_text(encoding="utf-8"))
    assert qor_metrics["schema_version"] == 3
    assert qor_metrics["tool"] == "ecc"
    assert qor_metrics["step"] == StepEnum.FLOORPLAN.value
    assert qor_metrics["design"] == "gcd"

    records = {record["id"]: record for record in qor_metrics["metrics"]}
    assert records["core_utilization"]["value"] == 0.42
    assert records["core_utilization"]["direction"] == "target_range"
    assert records["core_area"]["value"] == 1778.432
    assert records["die_area"]["unit"] == "um^2"
    assert {
        metric_id: (
            records[metric_id]["value"],
            records[metric_id]["source"]["selector"],
            records[metric_id]["rating"]["score"],
        )
        for metric_id in (
            "macro_count",
            "macro_area",
            "std_cell_count",
            "std_cell_area",
            "clock_count",
            "clock_area",
            "io_pad_count",
            "io_pad_area",
            "instance_area",
        )
    } == {
        "macro_count": (3, "/Instances/macros/num", False),
        "macro_area": (401.5, "/Instances/macros/area", False),
        "std_cell_count": (286, "/Instances/logic/num", False),
        "std_cell_area": (709.25, "/Instances/logic/area", False),
        "clock_count": (10, "/Instances/clock/num", False),
        "clock_area": (20, "/Instances/clock/area", False),
        "io_pad_count": (2, "/Instances/iopads/num", False),
        "io_pad_area": (10, "/Instances/iopads/area", False),
        "instance_area": (1200, "/Instances/total/area", False),
    }
    details = {detail["id"]: detail["summary"] for detail in qor_metrics["details"]}
    assert details["database_facts"]["layout"]["core_area"] == 1778.432
    assert details["database_facts"]["instance_total"]["count"] == 615
    assert {item["kind"] for item in details["database_facts"]["instance_classes"]} == {
        "clock",
        "iopads",
        "logic",
        "macros",
    }


def test_lvs_qor_metrics_include_connectivity_summary(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = build_step(
        workspace=workspace,
        step_name=StepEnum.LVS.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    build_step_space(step)
    assert step.feature.step is not None
    step.feature.step.write_text(
        json.dumps(
            {
                "entity": [{"entity": "nets", "netlist": 10, "def": 9, "difference": 1}],
                "connectivity": [
                    {"connectivity": "signals", "open": 1, "short": 0, "connected": 9, "total": 10}
                ],
                "violations": [
                    {"type": "open", "net": ["n1"], "terminals": ["A", "B"]},
                    {"type": "short", "net": "n2", "components": ["u1", "u2"]},
                ],
            }
        ),
        encoding="utf-8",
    )

    metrics = build_metrics_lvs(workspace, step)

    assert metrics is not None
    assert metrics.data["lvs_count"] == 2
    assert step.analysis.qor_summary is not None
    summary = json.loads(step.analysis.qor_summary.read_text(encoding="utf-8"))
    assert summary["quality_status"] == "blocked"
    assert summary["gates"] == [
        {
            "id": "qor.lvs.clean",
            "title": "Final LVS clean",
            "state": "failed",
            "blocking": True,
            "metrics": [
                {
                    "id": "lvs_count",
                    "actual": 2,
                    "operator": "==",
                    "expected": 0,
                    "source": {
                        "kind": "feature",
                        "path": "feature/lvs.step.json",
                        "selector": "/violations",
                    },
                }
            ],
            "evidence": [
                {
                    "kind": "feature",
                    "path": "feature/lvs.step.json",
                    "selector": "/violations",
                }
            ],
        }
    ]
    assert step.analysis.qor_metrics is not None
    details = {
        detail["id"]: detail
        for detail in json.loads(step.analysis.qor_metrics.read_text(encoding="utf-8"))["details"]
    }
    assert details["lvs_connectivity_summary"]["summary"] == {
        "schema_version": 1,
        "entities": [{"entity": "nets", "netlist": 10, "def": 9, "difference": 1}],
        "connectivity": [
            {"connectivity": "signals", "open": 1, "short": 0, "connected": 9, "total": 10}
        ],
        "violations": [
            {
                "type": "open",
                "net": "n1",
                "instance": "",
                "terminals": "A, B",
                "components": "",
            },
            {
                "type": "short",
                "net": "n2",
                "instance": "",
                "terminals": "",
                "components": "u1, u2",
            },
        ],
    }
