"""Pin the input each current-ledger step receives from its producers.

Execution, read-only projection, worker requests, and signoff collection are
covered separately so a consumer cannot silently diverge from the wired chain.
"""

import json
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest

from chipcompiler.data import OriginDesign, Workspace
from chipcompiler.data.step import recorded_step_directory
from chipcompiler.data.workspace.flow_data import build_dynamic_flow_data
from chipcompiler.data.workspace.flow_types import FlowDocument
from chipcompiler.engine.flow import EngineFlow
from chipcompiler.engine.workspace_flow import iter_workspace_steps
from chipcompiler.tools.ecc.builder import build_step as build_ecc_step
from chipcompiler.tools.kepler_formal.builder import build_step as build_kepler_step
from test.flow_fixture import step_directory

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


def _real_ledger(*, skip_steps=None) -> FlowDocument:
    flow_config: dict[str, object] = {"start_step": "route", "end_step": "Harden"}
    if skip_steps is not None:
        flow_config["skip_steps"] = list(skip_steps)
    return build_dynamic_flow_data(flow_config)


def _legacy_ledger() -> FlowDocument:
    """The same chain with the category keys removed (pre-#344 ledgers)."""
    data = _real_ledger()
    for step in data.get("steps", []):
        step.pop("category")
    return data


def _build(
    workspace,
    step_name,
    tool,
    input_def=None,
    input_verilog=None,
    input_db=None,
    *,
    step_directory=None,
):
    builder = build_kepler_step if tool in {"kepler_formal", "yosys_lec"} else build_ecc_step
    return builder(
        workspace=workspace,
        step_name=step_name,
        input_def=input_def,
        input_verilog=input_verilog,
        input_db=input_db,
        step_directory=step_directory,
    )


def _built(workspace, record):
    """The step *record* builds, in the directory the ledger records for it."""
    return _build(
        workspace,
        record["name"],
        record["tool"],
        step_directory=workspace.directory / recorded_step_directory(record),
    )


def _output_paths(workspace, ledger) -> dict[str, tuple[object, object]]:
    return {
        step["name"]: (_built(workspace, step).output.def_, _built(workspace, step).output.verilog)
        for step in ledger.get("steps", [])
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
        return _build(
            workspace,
            step,
            eda,
            input_def,
            input_verilog,
            input_db,
            step_directory=kwargs.get("step_directory"),
        )

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


def test_skipped_post_route_lec_keeps_the_same_sources(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    ledger = _real_ledger(skip_steps=("postRouteLec",))
    assert [step["name"] for step in ledger.get("steps", [])] == [
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
        next(step for step in ledger.get("steps", []) if step["name"] == "RCX")["input_step"] = (
            input_step
        )

    sources = _iterated_sources(_workspace(tmp_path), ledger)

    assert sources["RCX"] == expected


def _worker_payload(workspace, ledger, step_name) -> dict:
    """Wire *ledger* in the parent and write the step's req.json, as run_step does."""
    from chipcompiler.data.handshake import build_step_request, write_request

    flow = EngineFlow(workspace)
    flow.workspace.flow.data = ledger
    flow.create_step_workspaces(initialize_config=False)
    step = flow.get_workspace_step(step_name)
    assert step is not None
    request = build_step_request(
        workspace.directory,
        ledger.get("steps", []),
        step,
        attempt_id=f"attempt-{step_name}",
        layout_image=False,
    )
    write_request(request)
    return {"step_directory": str(request.directory), "attempt_id": request.attempt_id}


def _run_worker(monkeypatch, workspace, payload, run_step):
    from chipcompiler.engine import step_subprocess

    monkeypatch.setattr(
        "chipcompiler.data.load_workspace",
        lambda directory, *, read_only=False: workspace,
    )

    def initialize_db(flow, step):
        flow.engine_db = SimpleNamespace(engine=object(), initialization_error=None)

    monkeypatch.setattr(EngineFlow, "init_db_engine_for_step", initialize_db)
    monkeypatch.setattr(EngineFlow, "check_step_result", lambda self, workspace_step: True)
    monkeypatch.setattr(
        "chipcompiler.utility.log.capture_stdio_to_file", lambda _path: nullcontext()
    )
    return step_subprocess.run_step_worker(
        payload, {"events": []}, lambda: None, flow_factory=EngineFlow, tool_runner=run_step
    )


def test_worker_uses_persisted_explicit_input_step(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    ledger = _real_ledger()
    next(step for step in ledger.get("steps", []) if step["name"] == "RCX")["input_step"] = "route"
    payload = _worker_payload(workspace, ledger, "RCX")
    flow_path = tmp_path / "home" / "flow.json"
    flow_path.parent.mkdir(exist_ok=True)
    flow_path.write_text(json.dumps({"schema_version": 2, "steps": []}), encoding="utf-8")
    workspace.flow.path = flow_path
    workspace.flow.data = {}
    executed = {}

    def run_step(workspace, step, ecc_module=None):
        executed.update(name=step.name, input_def=step.input.def_)
        return True

    assert _run_worker(monkeypatch, workspace, payload, run_step)

    # The worker took its input from req.json: the ledger it reads is empty,
    # stays read-only and is never written.
    route = next(record for record in ledger.get("steps", []) if record["name"] == "route")
    assert executed == {"name": "RCX", "input_def": _built(workspace, route).output.def_}
    assert workspace.flow.read_only is True
    assert flow_path.read_text(encoding="utf-8") == json.dumps({"schema_version": 2, "steps": []})


def test_worker_evidence_code_reads_the_persisted_ledger(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    ledger = _real_ledger()
    payload = _worker_payload(workspace, ledger, "RCX")
    flow_path = tmp_path / "home" / "flow.json"
    flow_path.parent.mkdir(exist_ok=True)
    flow_path.write_text(json.dumps(ledger), encoding="utf-8")
    workspace.flow.path = flow_path
    workspace.flow.data = {}
    seen = []

    def run_step(workspace, step, ecc_module=None):
        # Checklist and QoR evidence code reads step states from the ledger.
        seen.extend(record["name"] for record in workspace.flow.steps())
        return True

    assert _run_worker(monkeypatch, workspace, payload, run_step)

    assert seen == [record["name"] for record in ledger.get("steps", [])]


def test_worker_builds_only_its_requested_step(tmp_path, monkeypatch):
    import chipcompiler.tools as tools

    workspace = _workspace(tmp_path)
    flow = EngineFlow(workspace)
    ledger: FlowDocument = {
        "schema_version": 2,
        "steps": [
            flow.init_flow_step("preFloorplan", "ecc", "Unstart"),
            flow.init_flow_step("place", "dreamplace", "Unstart"),
            flow.init_flow_step("CTS", "ecc", "Unstart"),
        ],
    }
    payload = _worker_payload(workspace, ledger, "preFloorplan")
    real_create_step = tools.create_step
    built = []

    def create_step(*args, **kwargs):
        built.append(kwargs["eda"])
        return real_create_step(*args, **kwargs)

    monkeypatch.setattr(tools, "create_step", create_step)
    executed = []

    def run_step(workspace, step, ecc_module=None):
        executed.append(step.name)
        return True

    assert _run_worker(monkeypatch, workspace, payload, run_step)

    # Unselected DreamPlace is never built, so its package is never imported.
    assert (built, executed) == (["ecc"], ["preFloorplan"])


@pytest.mark.parametrize("input_step", ["does_not_exist", "sta"])
def test_explicit_input_step_must_already_exist(tmp_path, input_step):
    from chipcompiler.data.workspace.flow_policy import FlowInputStepError

    ledger = _real_ledger()
    next(step for step in ledger.get("steps", []) if step["name"] == "RCX")["input_step"] = (
        input_step
    )

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

        def _analysis_issue(
            self,
            step_name: str,
            *,
            required: bool,
            reason: str,
            kind: str,
            label: str | None = None,
        ) -> Any:
            return None

    for step in ledger.get("steps", []):
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


def test_every_consumer_resolves_the_same_input_sources(tmp_path, monkeypatch):
    ledger = _real_ledger()
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
    next(step for step in ledger.get("steps", []) if step["name"] == "RCX")["input_step"] = (
        "does_not_exist"
    )

    with pytest.raises(FlowInputStepError):
        _recorded_sources(_workspace(tmp_path), ledger, monkeypatch)


def test_checker_batch_and_filler_sources_are_independent_policies(tmp_path, monkeypatch):
    ledger = {
        "schema_version": 2,
        "steps": [
            {
                "name": "route",
                "tool": "ecc",
                "category": "PNR",
                **step_directory("route", "ecc"),
            },
            {
                "name": "filler",
                "tool": "ecc",
                "category": "PNR",
                **step_directory("filler", "ecc"),
            },
            {
                "name": "lvs",
                "tool": "ecc",
                "category": "CHECKER",
                **step_directory("lvs", "ecc"),
            },
            {
                "name": "drc",
                "tool": "ecc",
                "category": "CHECKER",
                **step_directory("drc", "ecc"),
            },
            {
                "name": "RCX",
                "tool": "ecc",
                "category": "CHECKER",
                **step_directory("RCX", "ecc"),
            },
            {
                "name": "sta",
                "tool": "ecc",
                "category": "CHECKER",
                **step_directory("sta", "ecc"),
            },
            {
                "name": "powerAnalysis",
                "tool": "ecc",
                "category": "CHECKER",
                **step_directory("powerAnalysis", "ecc"),
            },
            {
                "name": "Harden",
                "tool": "ecc",
                "category": "PNR",
                **step_directory("Harden", "ecc"),
            },
        ],
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
        "schema_version": 2,
        "steps": [
            {
                "name": "route",
                "tool": "ecc",
                "category": "PNR",
                **step_directory("route", "ecc"),
            },
            {
                "name": "custom",
                "tool": "one",
                "category": "PNR",
                **step_directory("custom", "one"),
            },
        ],
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

    workspace.flow.path = workspace.directory / "home" / "flow.json"
    workspace.flow.path.parent.mkdir(exist_ok=True)
    flow = EngineFlow(workspace)
    flow.workspace.flow.data = copy.deepcopy(ledger)
    for step in flow.workspace.flow.steps():
        step["checklist_status"] = {"status": "blocked", "blocked": True}
    flow.save()
    prerequisite = {
        step["name"]: flow._blocked_checklist_prerequisite(
            EccStep(name=step["name"], tool=step["tool"])
        )
        for step in flow.workspace.flow.data.get("steps", [])
    }
    return {name: source for name, source in prerequisite.items() if source is not None}


def test_flow_category_rejects_a_ledger_without_categories():
    from chipcompiler.data.workspace.flow_policy import flow_category

    with pytest.raises(ValueError, match="no declared category"):
        flow_category(_legacy_ledger().get("steps", [])[0])
