import pytest

from chipcompiler.data import OriginDesign, Workspace
from chipcompiler.tools.ecc.lec_gates import post_route_lec_netlists


@pytest.mark.parametrize("checker_category", [None, "CHECKER"])
@pytest.mark.parametrize("explicit_input", [None, "lvs"])
def test_post_route_lec_gate_matches_execution_chain(tmp_path, checker_category, explicit_input):
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="design"))
    records = [
        {"name": "filler", "tool": "ecc"},
        {"name": "lvs", "tool": "ecc"},
        {"name": "drc", "tool": "ecc"},
        {"name": "postRouteLec", "tool": "yosys_lec", "category": "CHECKER"},
    ]
    if checker_category:
        for record in records[1:3]:
            record["category"] = checker_category
    if explicit_input:
        records[-1]["input_step"] = explicit_input
    workspace.flow.data = {"steps": records}

    _golden, gate = post_route_lec_netlists(workspace)

    source = explicit_input or ("filler" if checker_category else "drc")
    assert gate == tmp_path / f"{source}_ecc" / "output" / f"design_{source}.v.gz"
