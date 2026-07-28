import gzip
import json
from types import SimpleNamespace

from chipcompiler.data import (
    AnalysisPaths,
    ChecklistState,
    StepEnum,
    YosysFeature,
    YosysOutput,
    YosysReport,
)
from chipcompiler.tools.yosys.checklist import YosysSynthesisChecklist


def test_synthesis_checklist_records_current_mapped_netlist(tmp_path):
    netlist = tmp_path / "Synthesis_yosys" / "output" / "top_Synthesis.v.gz"
    netlist.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(netlist, "wt", encoding="utf-8") as file:
        file.write("module top(); endmodule\n")
    checklist_path = tmp_path / "Synthesis_yosys" / "checklist.json"
    step = SimpleNamespace(
        name=StepEnum.SYNTHESIS.value,
        checklist=ChecklistState(path=checklist_path),
        analysis=AnalysisPaths(),
        feature=YosysFeature(),
        report=YosysReport(),
        output=YosysOutput(verilog=netlist),
    )

    assert YosysSynthesisChecklist(SimpleNamespace(), step).check() is True

    data = json.loads(checklist_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 3
    assert data["checklist"] == [
        {
            "id": "artifact.synthesis.netlist",
            "step": "Synthesis",
            "category": "artifact",
            "owner": "checklist",
            "policy": "block",
            "state": "pass",
            "blocked": False,
            "title": "Mapped synthesis netlist",
            "summary": "Current output is present and non-empty.",
            "source": {
                "kind": "output",
                "path": str(netlist),
            },
            "evidence": [{"kind": "output", "path": str(netlist)}],
        }
    ]
