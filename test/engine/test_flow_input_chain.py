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


def test_signoff_steps_read_the_filler_output(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    sources = _recorded_sources(workspace, _real_ledger(), monkeypatch)

    assert sources == {
        "route": "origin",
        "filler": "route",
        "lvs": "filler",
        "drc": "filler",
        "antennaCheck": "filler",
        "postRouteLec": "filler",
        "RCX": "filler",
        "sta": "filler",
        "powerAnalysis": "filler",
        "emir": "filler",
        "Harden": "filler",
    }


def test_legacy_ledger_keeps_policy_sources_and_physical_chaining(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    sources = _recorded_sources(workspace, _legacy_ledger(), monkeypatch)

    assert sources == {
        "route": "origin",
        "filler": "route",
        "lvs": "filler",
        "drc": "filler",
        "antennaCheck": "filler",
        "postRouteLec": "filler",
        "RCX": "filler",
        "sta": "filler",
        "powerAnalysis": "filler",
        "emir": "filler",
        "Harden": "filler",
    }


def test_read_only_projection_matches_the_execution_chain_on_this_ledger(tmp_path):
    workspace = _workspace(tmp_path)
    sources = _iterated_sources(workspace, _real_ledger())

    assert sources == {
        "route": "origin",
        "filler": "route",
        "lvs": "filler",
        "drc": "filler",
        "antennaCheck": "filler",
        "postRouteLec": "filler",
        "RCX": "filler",
        "sta": "filler",
        "powerAnalysis": "filler",
        "emir": "filler",
        "Harden": "filler",
    }


def test_read_only_projection_follows_the_previous_step_without_category(tmp_path):
    workspace = _workspace(tmp_path)
    sources = _iterated_sources(workspace, _legacy_ledger())

    assert sources == {
        "route": "origin",
        "filler": "route",
        "lvs": "filler",
        "drc": "filler",
        "antennaCheck": "filler",
        "postRouteLec": "filler",
        "RCX": "filler",
        "sta": "filler",
        "powerAnalysis": "filler",
        "emir": "filler",
        "Harden": "filler",
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
        "antennaCheck": "filler",
        "RCX": "filler",
        "sta": "filler",
        "powerAnalysis": "filler",
        "emir": "filler",
        "Harden": "filler",
    }


@pytest.mark.parametrize("input_step,expected", [(None, "filler"), ("route", "route")])
def test_explicit_input_step_selects_the_named_step(tmp_path, input_step, expected):
    ledger = _real_ledger()
    if input_step is not None:
        next(step for step in ledger["steps"] if step["name"] == "RCX")["input_step"] = input_step

    sources = _iterated_sources(_workspace(tmp_path), ledger)

    assert sources["RCX"] == expected


@pytest.mark.parametrize("input_step", ["does_not_exist", "sta"])
def test_explicit_input_step_must_already_exist(tmp_path, input_step):
    from chipcompiler.data.workspace.flow_policy import FlowInputStepError

    ledger = _real_ledger()
    next(step for step in ledger["steps"] if step["name"] == "RCX")["input_step"] = input_step

    with pytest.raises(FlowInputStepError):
        _iterated_sources(_workspace(tmp_path), ledger)


def _signoff_sources(workspace, ledger):
    from chipcompiler.data import StateEnum
    from chipcompiler.engine.signoff.analysis import CollectorAnalysisMixin

    class _Collector(CollectorAnalysisMixin):
        def __init__(self, workspace):
            self.workspace = workspace
            self.refreshed = []

        def _refresh_step_analysis(self, step) -> None:
            self.refreshed.append(step)

        def _analysis_issue(self, step_name, *, required, reason, kind, label=None):
            return None

    for step in ledger["steps"]:
        step["state"] = StateEnum.Success.value
    workspace.flow.data = ledger
    workspace.flow.path = workspace.directory / "home" / "flow.json"
    collector = _Collector(workspace)
    collector._refresh_workspace_analysis(workspace.directory)
    outputs = _output_paths(workspace, ledger)
    return {
        step.name: _source_name(
            step.input.def_,
            getattr(step.input, "gate_verilog", None),
            outputs,
            workspace,
        )
        for step in collector.refreshed
    }


@pytest.mark.parametrize("legacy", [False, True])
def test_every_consumer_resolves_the_same_input_sources(tmp_path, monkeypatch, legacy):
    ledger = _legacy_ledger() if legacy else _real_ledger()
    workspace = _workspace(tmp_path)
    execution = _recorded_sources(workspace, ledger, monkeypatch)
    projection = _iterated_sources(workspace, ledger)
    signoff = _signoff_sources(workspace, ledger)

    assert projection == execution
    # The signoff analysis skips LEC steps; for every other step it must agree.
    assert signoff == {name: execution[name] for name in signoff}


def test_execution_rejects_a_missing_explicit_input(tmp_path, monkeypatch):
    from chipcompiler.data.workspace.flow_policy import FlowInputStepError

    ledger = _real_ledger()
    next(step for step in ledger["steps"] if step["name"] == "RCX")["input_step"] = "does_not_exist"

    with pytest.raises(FlowInputStepError):
        _recorded_sources(_workspace(tmp_path), ledger, monkeypatch)


def test_checker_batch_and_filler_sources_are_independent_policies(tmp_path, monkeypatch):
    ledger = {
        "steps": [
            {"name": "route", "tool": "ecc", "category": "PNR"},
            {"name": "filler", "tool": "ecc", "category": "PNR"},
            {"name": "lvs", "tool": "ecc", "category": "CHECKER"},
            {"name": "drc", "tool": "ecc", "category": "CHECKER"},
            {"name": "RCX", "tool": "ecc", "category": "CHECKER"},
            {"name": "sta", "tool": "ecc", "category": "CHECKER"},
            {"name": "powerAnalysis", "tool": "ecc", "category": "CHECKER"},
            {"name": "Harden", "tool": "ecc", "category": "PNR"},
        ]
    }

    sources = _recorded_sources(_workspace(tmp_path), ledger, monkeypatch)

    assert sources == {
        "route": "origin",
        "filler": "route",
        "lvs": "filler",
        "drc": "filler",
        "RCX": "filler",
        "sta": "filler",
        "powerAnalysis": "filler",
        "Harden": "filler",
    }


def test_an_unregistered_step_fails_loudly(tmp_path):
    from chipcompiler.data.workspace.flow_policy import FlowInputStepError

    ledger = {
        "steps": [
            {"name": "route", "tool": "ecc", "category": "PNR"},
            {"name": "custom", "tool": "one", "category": "PNR"},
        ]
    }

    with pytest.raises(FlowInputStepError, match="no flow policy registered"):
        _iterated_sources(_workspace(tmp_path), ledger)


def _post_route_gate_source(workspace, ledger) -> str:
    from chipcompiler.tools.ecc.lec_gates import _post_route_gate

    workspace.flow.data = ledger
    gate = _post_route_gate(workspace)
    return _source_name(None, gate, _output_paths(workspace, ledger), workspace)


def _checklist_prerequisite_sources(workspace, ledger) -> dict[str, str]:
    import copy

    from chipcompiler.data import EccStep
    from chipcompiler.engine.flow_completion import write_step_checklist

    workspace.flow.path = workspace.directory / "home" / "flow.json"
    workspace.flow.path.parent.mkdir(exist_ok=True)
    flow = EngineFlow(workspace)
    flow.workspace.flow.data = copy.deepcopy(ledger)
    for step in flow.workspace.flow.data["steps"]:
        write_step_checklist(
            flow,
            step,
            items=[],
            status={"status": "blocked", "blocked": True},
        )
    prerequisite = {
        step["name"]: flow._blocked_checklist_prerequisite(
            EccStep(name=step["name"], tool=step["tool"])
        )
        for step in flow.workspace.flow.data["steps"]
    }
    return {name: source for name, source in prerequisite.items() if source is not None}


@pytest.mark.parametrize("legacy", [False, True])
def test_post_route_gate_and_checker_chain_gate_semantics(tmp_path, monkeypatch, legacy):
    ledger = _legacy_ledger() if legacy else _real_ledger()
    workspace = _workspace(tmp_path)
    execution = _recorded_sources(workspace, ledger, monkeypatch)

    assert _post_route_gate_source(workspace, ledger) == execution["postRouteLec"]

    prerequisites = _checklist_prerequisite_sources(workspace, ledger)
    assert prerequisites == {"filler": "route", "Harden": "emir"}
