import gzip
import json
from pathlib import Path
from types import SimpleNamespace

from chipcompiler.tools.yosys.checklist import YosysSynthesisChecklist


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_json(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_synthesis_checklist_reads_gzip_mapped_netlist(tmp_path):
    rtl = _write_text(tmp_path / "rtl" / "top.v", "module top; endmodule\n")
    lib = _write_text(tmp_path / "lib" / "std.lib", "library(std) {}\n")
    log = _write_text(tmp_path / "Synthesis_yosys" / "log" / "Synthesis.log", "End of script.\n")
    metrics = _write_json(
        tmp_path / "Synthesis_yosys" / "analysis" / "qor_metrics.json",
        {
            "schema_version": 3,
            "metrics": [
                {"id": "synthesis_cell_count", "value": 1},
                {"id": "synthesis_cell_area", "value": 1.0},
            ],
        },
    )
    stat = _write_json(
        tmp_path / "Synthesis_yosys" / "feature" / "Synthesis_stat.json",
        {
            "modules": {"top": {}},
            "design": {"num_cells": 1, "area": 1.0},
            "invocation": "stat -liberty std.lib",
        },
    )
    netlist = tmp_path / "Synthesis_yosys" / "output" / "top_Synthesis.v.gz"
    netlist.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(netlist, "wt", encoding="utf-8") as file:
        file.write("module top();\n  BUFX4 u0();\nendmodule\n")

    checklist_path = tmp_path / "Synthesis_yosys" / "checklist.json"
    workspace = SimpleNamespace(
        design=SimpleNamespace(input_filelist="", top_module="top", name="top"),
        parameters=SimpleNamespace(data={"Frequency max [MHz]": 100}),
        pdk=SimpleNamespace(libs=[str(lib)]),
        home=SimpleNamespace(update_checklist=lambda **kwargs: None),
    )
    step = SimpleNamespace(
        name="Synthesis",
        input={"verilog": str(rtl)},
        analysis={"metrics": str(metrics)},
        feature={"stat": str(stat)},
        log={"file": str(log)},
        output={"verilog": str(netlist)},
        checklist={"path": str(checklist_path)},
    )

    assert YosysSynthesisChecklist(workspace, step).check() is True

    data = json.loads(checklist_path.read_text(encoding="utf-8"))
    netlist_item = next(item for item in data["checklist"] if item["type"] == "Netlist")
    assert netlist_item["state"] == "Passed"
    assert netlist_item["info"] == ""
