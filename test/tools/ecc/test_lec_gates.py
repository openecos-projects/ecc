from typing import cast

import pytest

from chipcompiler.data import OriginDesign, StateEnum, Workspace
from chipcompiler.data.workspace.flow_types import FlowDocument, FlowStepEntry
from chipcompiler.tools.ecc.lec_gates import post_route_lec_netlists
from test.flow_fixture import step_fields


@pytest.mark.parametrize("checker_category", [None, "CHECKER"])
@pytest.mark.parametrize("explicit_input", [None, "lvs"])
def test_post_route_lec_gate_matches_execution_chain(tmp_path, checker_category, explicit_input):
    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="design"))
    records = [
        {"state": "Unstart", "name": "filler", "tool": "ecc"},
        {"state": "Unstart", "name": "lvs", "tool": "ecc"},
        {"state": "Unstart", "name": "drc", "tool": "ecc"},
        {"state": "Unstart", "name": "antennaCheck", "tool": "ecc"},
        {
            "state": "Unstart",
            "name": "postRouteLec",
            "tool": "kepler_formal",
            "category": "CHECKER",
        },
    ]
    if checker_category:
        for record in records[1:3]:
            record["category"] = checker_category
    if explicit_input:
        records[-1]["input_step"] = explicit_input
    from test.flow_fixture import current_flow_document

    workspace.flow.data = current_flow_document(records)

    _golden, gate = post_route_lec_netlists(workspace)

    source = explicit_input or "filler"
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
        {"state": "Unstart", "name": "route", "tool": "ecc", "category": "PNR"},
        {"state": "Unstart", "name": "filler", "tool": "ecc", "category": "PNR"},
        {"state": "Unstart", "name": "drc", "tool": "ecc", "category": "CHECKER"},
        {"state": "Unstart", "name": "emir", "tool": "ecc", "category": "PNR"},
        {"state": "Unstart", "name": "sta", "tool": "ecc", "category": "PNR"},
    ]
    from test.flow_fixture import current_flow_document

    workspace.flow.data = current_flow_document(records)
    _write_pnr_outputs(tmp_path, records)

    # drc and emir are skipped; sta is the latest declared PNR output.
    assert latest_pnr_output(workspace, ".v.gz") == (
        tmp_path / "sta_ecc" / "output" / "design_sta.v.gz"
    )


def test_latest_pnr_output_rejects_a_step_without_a_category(tmp_path):
    from chipcompiler.tools.ecc.lec_gates import latest_pnr_output

    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="design"))
    records = [
        {"state": "Unstart", "name": "filler", "tool": "ecc", "category": "PNR"},
        {"state": "Unstart", "name": "drc", "tool": "ecc", "category": "CHECKER"},
        {"state": "Unstart", "name": "sta", "tool": "ecc"},
    ]
    from test.flow_fixture import current_flow_document

    document = cast(dict, current_flow_document(records))
    del document["steps"][-1]["category"]
    workspace.flow.data = cast(FlowDocument, document)

    with pytest.raises(ValueError, match="no declared category"):
        latest_pnr_output(workspace, ".v.gz")


def test_latest_pnr_output_rejects_info_only_category(tmp_path):
    from chipcompiler.tools.ecc.lec_gates import latest_pnr_output

    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="design"))
    records = [
        {"state": "Unstart", "name": "filler", "tool": "ecc", "category": "PNR"},
        {"state": "Unstart", "name": "drc", "tool": "ecc", "info": {"category": "CHECKER"}},
    ]
    from test.flow_fixture import current_flow_document

    document = cast(dict, current_flow_document(records))
    del document["steps"][-1]["category"]
    workspace.flow.data = cast(FlowDocument, document)
    _write_pnr_outputs(tmp_path, records)

    with pytest.raises(ValueError, match="no declared category"):
        latest_pnr_output(workspace, ".v.gz")


def test_latest_pnr_output_rejects_an_unregistered_step(tmp_path):
    from chipcompiler.tools.ecc.lec_gates import latest_pnr_output

    workspace = Workspace(directory=tmp_path, design=OriginDesign(name="design"))
    workspace.flow.data = {
        "schema_version": 2,
        "steps": [
            FlowStepEntry(
                name="custom",
                tool="one",
                state="Unstart",
                category="PNR",
                directory="custom_one",
            )
        ],
    }

    with pytest.raises(ValueError, match="no flow policy registered"):
        latest_pnr_output(workspace, ".v.gz")


@pytest.mark.parametrize(
    ("declared", "with_synthesis", "expected"),
    [
        (True, True, "inputs/gcd_golden.v"),
        (False, True, "Synthesis_yosys/output/gcd_Synthesis.v.gz"),
        (False, False, "origin/gcd.v"),
    ],
)
def test_post_route_lec_is_revalidated_against_the_golden_it_ran_with(
    tmp_path, declared, with_synthesis, expected
):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", origin_verilog=tmp_path / "origin/gcd.v"),
    )
    if declared:
        workspace.design.golden_verilog = tmp_path / "inputs/gcd_golden.v"
    steps = [("filler", "ecc"), ("lvs", "ecc"), ("postRouteLec", "kepler_formal")]
    if with_synthesis:
        steps.insert(0, ("Synthesis", "yosys"))
    workspace.flow.data = {
        "schema_version": 2,
        "steps": [
            {
                "name": name,
                "tool": tool,
                "state": StateEnum.Success.value,
                **step_fields(name, tool),
            }
            for name, tool in steps
        ],
    }

    # Execution's order (engine/flow.py): the declared golden, the synthesis
    # netlist, the origin.
    assert post_route_lec_netlists(workspace)[0] == tmp_path / expected
