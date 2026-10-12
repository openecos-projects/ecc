from pathlib import Path
from types import SimpleNamespace

from chipcompiler.cli.project.run_preflight import build_run_preflight, output_paths
from chipcompiler.data.workspace.layout import OutputPaths, StepInput


def test_build_run_preflight_reports_missing_inputs(tmp_path):
    existing = tmp_path / "input.v"
    existing.write_text("module top; endmodule\n")
    missing = tmp_path / "missing.def"
    flow = SimpleNamespace(
        workspace_steps=[
            SimpleNamespace(
                name="place",
                tool="ecc",
                input=StepInput(verilog=existing, def_=missing),
                output=OutputPaths(),
            )
        ]
    )

    result = build_run_preflight(flow, ["place"], only="place", force=False)

    assert result["ready"] is False
    assert result["selected_steps"][0]["tool"] == "ecc"
    assert result["missing_inputs"] == [
        {"step": "place", "input": "def", "path": str(missing)}
    ]


def test_output_paths_serializes_declared_paths(tmp_path):
    output = tmp_path / "out.v"
    flow = SimpleNamespace(
        workspace_steps=[
            SimpleNamespace(
                name="synthesis",
                output=OutputPaths(verilog=output, db=None),
            )
        ]
    )

    assert output_paths(flow, ["synthesis"]) == {"synthesis": [str(output)]}
