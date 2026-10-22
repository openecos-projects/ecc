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
        {"name": "antennaCheck", "tool": "ecc"},
        {"name": "postRouteLec", "tool": "yosys_lec", "category": "CHECKER"},
    ]
    if checker_category:
        for record in records[1:3]:
            record["category"] = checker_category
    if explicit_input:
        records[-1]["input_step"] = explicit_input
    workspace.flow.data = {"steps": records}

    _golden, gate = post_route_lec_netlists(workspace)

    source = explicit_input or "drc"
    assert gate == tmp_path / f"{source}_ecc" / "output" / f"design_{source}.v.gz"


def _write_pnr_outputs(tmp_path, records):
    for record in records:
        output_dir = tmp_path / f"{record['name']}_{record['tool']}" / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"design_{record['name']}.v.gz").write_bytes(b"")


def test_latest_pnr_output_skips_declared_checkers_and_advisory_steps(tmp_path):
    from chipcompiler.tools.ecc.lec_gates import latest_pnr_output

    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="design"))
    records = [
        {"name": "route", "tool": "ecc", "category": "PNR"},
        {"name": "filler", "tool": "ecc", "category": "PNR"},
        {"name": "drc", "tool": "ecc", "category": "CHECKER"},
        {"name": "emir", "tool": "ecc", "category": "PNR"},
        {"name": "sta", "tool": "ecc"},
    ]
    workspace.flow.data = {"steps": records}
    _write_pnr_outputs(tmp_path, records)

    # `drc` declares CHECKER and `emir` is advisory, so both are skipped. A
    # category-less ledger treats every step as PNR for chaining, so `sta` is
    # the latest PNR output.
    assert latest_pnr_output(workspace, ".v.gz") == (
        tmp_path / "sta_ecc" / "output" / "design_sta.v.gz"
    )


def test_latest_pnr_output_honors_the_info_category_fallback(tmp_path):
    from chipcompiler.tools.ecc.lec_gates import latest_pnr_output

    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="design"))
    records = [
        {"name": "filler", "tool": "ecc", "category": "PNR"},
        {"name": "drc", "tool": "ecc", "info": {"category": "CHECKER"}},
    ]
    workspace.flow.data = {"steps": records}
    _write_pnr_outputs(tmp_path, records)

    assert latest_pnr_output(workspace, ".v.gz") == (
        tmp_path / "filler_ecc" / "output" / "design_filler.v.gz"
    )
