"""Pins which input each step receives before the input-source rule is unified.

Two ledgers cover the current split: a ledger built from ``flow_config`` (the
shape every real workspace has, with ``category``) and a legacy ledger without
``category``. Consumers are pinned separately and are allowed to disagree; this
module does not assert that they agree.
"""

import pytest

from chipcompiler.data import OriginDesign, Workspace
from chipcompiler.data.workspace.flow_data import build_dynamic_flow_data
from chipcompiler.engine.flow import EngineFlow
from chipcompiler.engine.workspace_flow import iter_workspace_steps
from chipcompiler.tools.ecc.builder import build_step as build_ecc_step
from chipcompiler.tools.kepler_formal.builder import build_step as build_kepler_step

_ROUTE_TO_HARDEN = ("route", "filler", "lvs", "drc", "antennaCheck", "postRouteLec", "RCX", "sta")


def _workspace(tmp_path) -> Workspace:
    return Workspace(
        directory=tmp_path,
        design=OriginDesign(
            name="gcd",
            top_module="gcd",
            origin_def=tmp_path / "origin.def",
            origin_verilog=tmp_path / "origin.v",
        ),
    )


def _real_ledger(*, skip_steps=None) -> dict:
    flow_config = {"start_step": "route", "end_step": "Harden"}
    if skip_steps is not None:
        flow_config["skip_steps"] = list(skip_steps)
    return build_dynamic_flow_data(flow_config)


def _legacy_ledger() -> dict:
    """The same chain with the category keys removed (pre-#344 ledgers)."""
    data = _real_ledger()
    for step in data["steps"]:
        step.pop("category")
    return data


def _build(workspace, step_name, tool, input_def=None, input_verilog=None, input_db=None):
    builder = build_kepler_step if tool in {"kepler_formal", "yosys_lec"} else build_ecc_step
    return builder(
        workspace=workspace,
        step_name=step_name,
        input_def=input_def,
        input_verilog=input_verilog,
        input_db=input_db,
    )


def _output_paths(workspace, ledger) -> dict[str, tuple[object, object]]:
    return {
        step["name"]: (
            _build(workspace, step["name"], step["tool"]).output.def_,
            _build(workspace, step["name"], step["tool"]).output.verilog,
        )
        for step in ledger["steps"]
    }


def _source_name(input_def, input_verilog, output_paths, workspace) -> str:
    """Name the step a builder input came from.

    LEC builders record the chained netlist as ``input.gate_verilog`` and leave
    ``input.def_`` unset, so the verilog path is the fallback identity.
    """
    if input_def == workspace.design.origin_def or input_verilog == workspace.design.origin_verilog:
        return "origin"
    for name, (def_path, verilog_path) in output_paths.items():
        if input_def is not None and input_def == def_path:
            return name
        if input_verilog is not None and input_verilog == verilog_path:
            return name
    return f"unknown:{input_def}:{input_verilog}"


def _recorded_sources(workspace, ledger, monkeypatch):
    import chipcompiler.tools as tools

    recorded = {}

    def create_step(workspace, step, eda, input_def, input_verilog, input_db=None, **kwargs):
        recorded[step] = (input_def, input_verilog)
        return _build(workspace, step, eda, input_def, input_verilog, input_db)

    monkeypatch.setattr(tools, "create_step", create_step)
    flow = EngineFlow(workspace=workspace)
    flow.workspace.flow.data = ledger
    flow.create_step_workspaces()
    output_paths = _output_paths(workspace, ledger)
    return {
        step: _source_name(input_def, input_verilog, output_paths, workspace)
        for step, (input_def, input_verilog) in recorded.items()
    }


def _iterated_sources(workspace, ledger):
    workspace.flow.data = ledger
    output_paths = _output_paths(workspace, ledger)
    return {
        workspace_step.name: _source_name(
            workspace_step.input.def_,
            getattr(workspace_step.input, "gate_verilog", None),
            output_paths,
            workspace,
        )
        for _flow_step, workspace_step in iter_workspace_steps(workspace)
        if workspace_step is not None
    }


def test_category_ledger_reads_the_latest_pnr_step(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    sources = _recorded_sources(workspace, _real_ledger(), monkeypatch)

    assert sources == {
        "route": "origin",
        "filler": "route",
        "lvs": "filler",
        "drc": "filler",
        "antennaCheck": "drc",
        "postRouteLec": "filler",
        "RCX": "filler",
        "sta": "filler",
        "powerAnalysis": "filler",
        "emir": "powerAnalysis",
        "Harden": "powerAnalysis",
    }


def test_legacy_ledger_without_category_chains_every_step(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    sources = _recorded_sources(workspace, _legacy_ledger(), monkeypatch)

    assert sources == {
        "route": "origin",
        "filler": "route",
        "lvs": "filler",
        "drc": "lvs",
        "antennaCheck": "drc",
        "postRouteLec": "drc",
        "RCX": "drc",
        "sta": "RCX",
        "powerAnalysis": "sta",
        "emir": "powerAnalysis",
        "Harden": "powerAnalysis",
    }


def test_read_only_projection_matches_the_execution_chain_on_this_ledger(tmp_path):
    workspace = _workspace(tmp_path)
    sources = _iterated_sources(workspace, _real_ledger())

    assert sources == {
        "route": "origin",
        "filler": "route",
        "lvs": "filler",
        "drc": "filler",
        "antennaCheck": "drc",
        "postRouteLec": "filler",
        "RCX": "filler",
        "sta": "filler",
        "powerAnalysis": "filler",
        "emir": "powerAnalysis",
        "Harden": "powerAnalysis",
    }


def test_read_only_projection_follows_the_previous_step_without_category(tmp_path):
    workspace = _workspace(tmp_path)
    sources = _iterated_sources(workspace, _legacy_ledger())

    assert sources == {
        "route": "origin",
        "filler": "route",
        "lvs": "filler",
        "drc": "lvs",
        "antennaCheck": "drc",
        "postRouteLec": "drc",
        "RCX": "drc",
        "sta": "RCX",
        "powerAnalysis": "sta",
        "emir": "powerAnalysis",
        "Harden": "powerAnalysis",
    }


def test_skipped_post_route_lec_keeps_the_same_sources(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    ledger = _real_ledger(skip_steps=("postRouteLec",))
    assert [step["name"] for step in ledger["steps"]] == [
        "route",
        "filler",
        "lvs",
        "drc",
        "antennaCheck",
        "RCX",
        "sta",
        "powerAnalysis",
        "emir",
        "Harden",
    ]

    sources = _recorded_sources(workspace, ledger, monkeypatch)

    assert sources == {
        "route": "origin",
        "filler": "route",
        "lvs": "filler",
        "drc": "filler",
        "antennaCheck": "drc",
        "RCX": "filler",
        "sta": "filler",
        "powerAnalysis": "filler",
        "emir": "powerAnalysis",
        "Harden": "powerAnalysis",
    }


@pytest.mark.parametrize("input_step", [None, "route", "does_not_exist"])
def test_explicit_input_step_resolution(tmp_path, input_step):
    ledger = _real_ledger()
    rcx = next(step for step in ledger["steps"] if step["name"] == "RCX")
    if input_step is not None:
        rcx["input_step"] = input_step
    workspace = _workspace(tmp_path)

    sources = _iterated_sources(workspace, ledger)

    # An explicit input names a created step; a missing one silently falls back
    # to the origin today.
    assert sources["RCX"] == {"route": "route", "does_not_exist": "origin"}.get(
        input_step, "filler"
    )
