import json
from hashlib import sha256
from types import SimpleNamespace

import pytest

import chipcompiler.engine.flow as flow_module
from chipcompiler import tools
from chipcompiler.data import (
    EccFeature,
    EccOutput,
    EccStep,
    StateEnum,
    StepEnum,
    StepMetrics,
    Workspace,
    YosysOutput,
    YosysStep,
)
from chipcompiler.data.workspace import Flow
from chipcompiler.engine.flow import EngineFlow


def test_engine_flow_missing_path_is_not_initialized():
    engine_flow = EngineFlow(Workspace())

    assert engine_flow.has_init() is False


def test_engine_flow_persists_run_facts_before_refreshing_qor_analysis(
    monkeypatch,
    tmp_path,
):
    (tmp_path / "home").mkdir(exist_ok=True)
    workspace = Workspace(directory=tmp_path, flow=Flow(path=tmp_path / "home" / "flow.json"))
    step_feature = tmp_path / "feature" / "route.step.json"
    sdc_path = tmp_path / "gcd.sdc"
    sdc_contents = "create_clock -name clk -period 2 [get_ports clk]\n"
    sdc_path.write_text(sdc_contents, encoding="utf-8")
    workspace.pdk.sdc = sdc_path
    step_feature.parent.mkdir()
    step_feature.write_text(json.dumps({"route": {"DR": []}}), encoding="utf-8")
    workspace_step = EccStep(
        name="route",
        directory=tmp_path,
        tool="ecc",
        feature=EccFeature(step=step_feature),
    )
    engine_flow = EngineFlow(workspace)
    engine_flow.workspace.flow.data = {
        "steps": [{"name": "route", "tool": "ecc", "state": "Unstart"}],
    }
    engine_flow.workspace_steps = [workspace_step]
    engine_flow.engine_db = SimpleNamespace(engine=None)
    refreshed = []

    monkeypatch.setattr(tools, "run_step", lambda **_kwargs: True)
    monkeypatch.setattr(engine_flow, "check_step_result", lambda **_kwargs: True)
    monkeypatch.setattr(tools, "save_layout_image", lambda **_kwargs: True)

    def refresh_metrics(*, workspace, step):
        refreshed.append(json.loads(step.feature.step.read_text(encoding="utf-8")))
        return StepMetrics(data={"Tool": step.tool})

    monkeypatch.setattr(tools, "build_step_metrics", refresh_metrics)

    assert engine_flow.run_step(workspace_step) == StateEnum.Success

    assert refreshed and refreshed[0]["route"] == {"DR": []}
    run = refreshed[0]["run"]
    assert run["state"] == StateEnum.Success.value
    assert run["runtime_seconds"] >= 0
    assert run["peak_memory_mb"] >= 0
    assert refreshed[0]["constraints"] == {
        "sdc": {
            "availability": "available",
            "sha256": sha256(sdc_contents.encode("utf-8")).hexdigest(),
            "size_bytes": len(sdc_contents.encode("utf-8")),
        }
    }


def test_engine_flow_does_not_delay_short_step_before_return(monkeypatch, tmp_path):
    workspace = Workspace()
    workspace.flow.data = {
        "steps": [{"name": "route", "tool": "ecc", "state": "Unstart"}],
    }
    engine_flow = EngineFlow(workspace)
    workspace_step = EccStep(name="route", directory=tmp_path, tool="ecc")
    engine_flow.workspace_steps = [workspace_step]
    engine_flow.engine_db = SimpleNamespace(engine=None)
    sleep_calls = []

    monkeypatch.setattr(tools, "run_step", lambda **_kwargs: False)
    monkeypatch.setattr(flow_module.time, "sleep", sleep_calls.append)

    assert engine_flow.run_step(workspace_step) is StateEnum.Imcomplete
    assert sleep_calls == []


def test_end_marker_follows_step_writes_and_precedes_completion(monkeypatch, tmp_path):
    """The end marker fires after all step-scoped writes and before completion notify."""
    import chipcompiler.runtime.log_stream as log_stream_module

    (tmp_path / "home").mkdir(exist_ok=True)
    workspace = Workspace(directory=tmp_path, flow=Flow(path=tmp_path / "home" / "flow.json"))
    workspace_step = EccStep(
        name="route",
        directory=tmp_path,
        tool="ecc",
        feature=EccFeature(step=tmp_path / "route.feature.json"),
    )
    engine_flow = EngineFlow(workspace)
    engine_flow.workspace.flow.data = {
        "steps": [{"name": "route", "tool": "ecc", "state": "Unstart"}],
    }
    engine_flow.workspace_steps = [workspace_step]
    engine_flow.engine_db = SimpleNamespace(engine=None)

    events: list[tuple[str, object]] = []

    monkeypatch.setattr(tools, "run_step", lambda **_kwargs: True)
    monkeypatch.setattr(engine_flow, "check_step_result", lambda **_kwargs: True)
    monkeypatch.setattr(
        tools,
        "build_step_metrics",
        lambda **_kwargs: events.append(("qor", None)) or {},
    )
    monkeypatch.setattr(
        tools,
        "save_layout_image",
        lambda **_kwargs: events.append(("layout", None)),
    )

    original_set_state = engine_flow.set_state

    def recording_set_state(**kwargs):
        events.append(("set_state", kwargs.get("state")))
        return original_set_state(**kwargs)

    monkeypatch.setattr(engine_flow, "set_state", recording_set_state)
    monkeypatch.setattr(
        engine_flow,
        "clear_db_engine_after_step",
        lambda step, state: events.append(("db_cleanup", state)),
    )
    monkeypatch.setattr(
        log_stream_module,
        "emit_step_marker",
        lambda event, *, step, tool: events.append(("marker", event)),
    )

    class CompletionObserver:
        def on_step_completed(self, step, state):
            # The end marker must already have fired when completion is notified.
            assert ("marker", "end") in events
            events.append(("observer", "completed"))

    result = engine_flow.run_step(workspace_step, observer=CompletionObserver())

    assert result == StateEnum.Success
    end_index = events.index(("marker", "end"))
    assert events.index(("set_state", StateEnum.Success)) < end_index
    assert events.index(("qor", None)) < end_index
    assert events.index(("layout", None)) < end_index
    assert events.index(("db_cleanup", StateEnum.Success)) < end_index
    assert end_index < events.index(("observer", "completed"))


def test_end_marker_suppressed_when_final_state_persistence_fails(monkeypatch, tmp_path):
    """A failed final save downgrades the step and suppresses the end marker."""
    import chipcompiler.runtime.log_stream as log_stream_module

    workspace = Workspace()
    workspace.flow.data = {
        "steps": [{"name": "route", "tool": "ecc", "state": "Unstart"}],
    }
    workspace_step = EccStep(name="route", directory=tmp_path, tool="ecc")
    engine_flow = EngineFlow(workspace)
    engine_flow.workspace_steps = [workspace_step]
    engine_flow.engine_db = SimpleNamespace(engine=None)

    events = []
    monkeypatch.setattr(tools, "run_step", lambda **_kwargs: True)
    monkeypatch.setattr(engine_flow, "check_step_result", lambda **_kwargs: True)
    monkeypatch.setattr(engine_flow, "save", lambda: False)
    monkeypatch.setattr(
        log_stream_module,
        "emit_step_marker",
        lambda event, *, step, tool: events.append(("marker", event)),
    )

    completed_states = []

    class CompletionObserver:
        def on_step_completed(self, step, state):
            completed_states.append(state)

    result = engine_flow.run_step(workspace_step, observer=CompletionObserver())

    assert result == StateEnum.Imcomplete
    assert ("marker", "begin") in events
    assert ("marker", "end") not in events
    assert completed_states == [StateEnum.Imcomplete]


def test_check_step_result_synthesis_uses_common_verilog(tmp_path):
    verilog = tmp_path / "gcd.v"
    verilog.write_text("module gcd; endmodule\n")
    step = YosysStep(name=StepEnum.SYNTHESIS.value, output=YosysOutput(verilog=verilog))
    assert EngineFlow(Workspace()).check_step_result(step) is True


def test_check_step_result_harden_reads_ecc_only_lef_lib(tmp_path):
    lef = tmp_path / "gcd.lef"
    lib = tmp_path / "gcd.lib"
    lef.write_text("")
    lib.write_text("")
    step = EccStep(name=StepEnum.HARDEN.value, output=EccOutput(lef=lef, lib=lib))
    assert EngineFlow(Workspace()).check_step_result(step) is True
    # missing lib -> not success
    step_missing = EccStep(
        name=StepEnum.HARDEN.value,
        output=EccOutput(lef=lef, lib=tmp_path / "missing.lib"),
    )
    assert EngineFlow(Workspace()).check_step_result(step_missing) is False


def test_check_step_result_default_requires_def_verilog_gds(tmp_path):
    for name in ("gcd.def", "gcd.v", "gcd.gds"):
        (tmp_path / name).write_text("")
    step = EccStep(
        name=StepEnum.PLACEMENT.value,
        output=EccOutput(
            def_=tmp_path / "gcd.def",
            verilog=tmp_path / "gcd.v",
            gds=tmp_path / "gcd.gds",
        ),
    )
    assert EngineFlow(Workspace()).check_step_result(step) is True


def test_check_step_result_timing_opt_does_not_require_gds(tmp_path):
    (tmp_path / "gcd.def").write_text("")
    (tmp_path / "gcd.v").write_text("")
    step = EccStep(
        name=StepEnum.TIMING_OPT.value,
        output=EccOutput(def_=tmp_path / "gcd.def", verilog=tmp_path / "gcd.v"),
    )
    # gds intentionally absent; timing-opt result must still succeed.
    assert EngineFlow(Workspace()).check_step_result(step) is True


@pytest.mark.parametrize(
    "spef_paths",
    [
        pytest.param([], id="empty"),
        pytest.param(None, id="nonempty"),  # replaced with tmp_path-based list below
    ],
)
def test_rcx_to_sta_spef_transfer(monkeypatch, tmp_path, spef_paths):
    # create_step_workspaces copies the RCX step's spef list onto the following
    # STA step. The legacy `get("spef", [])` forwarded the predecessor's own list
    # object even when empty, so the handoff must preserve object identity (not
    # substitute a fresh list) for both the empty and nonempty cases.
    import chipcompiler.tools as tools_api
    from chipcompiler.data import OriginDesign

    if spef_paths is None:
        spef_paths = [tmp_path / "gcd_c.spef", tmp_path / "gcd_r.spef"]

    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )

    rcx_output = EccOutput(spef=spef_paths)
    prebuilt = {
        StepEnum.RCX.value: EccStep(name=StepEnum.RCX.value, tool="ecc", output=rcx_output),
        StepEnum.STA.value: EccStep(name=StepEnum.STA.value, tool="ecc"),
    }

    def fake_create_step(workspace, step, eda, **kwargs):
        return prebuilt[step]

    monkeypatch.setattr(tools_api, "create_step", fake_create_step)

    flow = EngineFlow(workspace)
    # load() leaves flow.data empty (no flow.path); set the steps for this test.
    flow.workspace.flow.data = {
        "steps": [
            {"name": StepEnum.RCX.value, "tool": "ecc"},
            {"name": StepEnum.STA.value, "tool": "ecc"},
        ]
    }
    flow.create_step_workspaces()

    sta_step = flow.get_workspace_step(StepEnum.STA.value)
    assert isinstance(sta_step, EccStep)
    assert sta_step.output.spef == spef_paths  # content transferred from RCX
    assert sta_step.output.spef is rcx_output.spef  # same object, per legacy contract


def test_executable_steps_filter_chains_success_predecessor(monkeypatch, tmp_path):
    # create_step_workspaces(executable_steps=...) builds non-executing steps
    # without a dependency check, so a Success predecessor whose tool is missing
    # still chains its outputs to the executing successor and marks nothing
    # Incomplete.
    workspace = Workspace(
        directory=tmp_path,
        flow=Flow(path=tmp_path / "home" / "flow.json"),
    )
    flow = EngineFlow(workspace)
    # EngineFlow construction loads (and resets) flow.data; set steps after.
    flow.workspace.flow.data = {
        "steps": [
            {"name": "syn", "tool": "missing-tool", "state": StateEnum.Success.value},
            {"name": "floorplan", "tool": "ecc", "state": StateEnum.Unstart.value},
        ]
    }

    predecessor_output = EccOutput(
        def_=tmp_path / "syn.def",
        verilog=tmp_path / "syn.v",
        db=tmp_path / "syn.db",
    )
    prebuilt = {
        "syn": EccStep(name="syn", tool="missing-tool", output=predecessor_output),
        "floorplan": EccStep(name="floorplan", tool="ecc"),
    }
    calls = []

    def fake_create_step(workspace, step, eda, *, check_dependency, **kwargs):
        calls.append({"step": step, "check_dependency": check_dependency, "inputs": kwargs})
        # Mirror the load_eda_module contract: a missing tool fails the build
        # only when the dependency check actually runs.
        if check_dependency and eda == "missing-tool":
            return None
        return prebuilt[step]

    monkeypatch.setattr(tools, "create_step", fake_create_step)

    flow.create_step_workspaces(executable_steps={"floorplan"})

    assert [call["check_dependency"] for call in calls] == [False, True]
    successor_inputs = calls[1]["inputs"]
    assert successor_inputs["input_def"] == predecessor_output.def_
    assert successor_inputs["input_verilog"] == predecessor_output.verilog
    assert successor_inputs["input_db"] == predecessor_output.db
    assert [step.name for step in flow.workspace_steps] == ["syn", "floorplan"]
    assert all(
        step.get("state") != StateEnum.Imcomplete.value
        for step in flow.workspace.flow.data["steps"]
    )


# --- Phase 2: Silent failure regression tests ---


class TestCheckStepResultRcx:
    """Regression: RCX check_step_result was always True (bug fixed in Phase 1)."""

    def test_rcx_fails_when_spef_missing(self, tmp_path):
        spef = tmp_path / "missing.spef"
        step = EccStep(
            name=StepEnum.RCX.value,
            output=EccOutput(spef=[spef]),
        )
        assert EngineFlow(Workspace()).check_step_result(step) is False

    def test_rcx_succeeds_when_all_spef_exist(self, tmp_path):
        spef1 = tmp_path / "corner1.spef"
        spef2 = tmp_path / "corner2.spef"
        spef1.write_text("")
        spef2.write_text("")
        step = EccStep(
            name=StepEnum.RCX.value,
            output=EccOutput(spef=[spef1, spef2]),
        )
        assert EngineFlow(Workspace()).check_step_result(step) is True

    def test_rcx_succeeds_with_empty_spef_list(self):
        step = EccStep(
            name=StepEnum.RCX.value,
            output=EccOutput(spef=[]),
        )
        assert EngineFlow(Workspace()).check_step_result(step) is True


class TestStepExceptionForcesIncomplete:
    """Regression: tool exception should force Incomplete, never Success."""

    def test_exception_forces_incomplete(self, monkeypatch, tmp_path):
        workspace = Workspace()
        workspace.flow.data = {
            "steps": [{"name": "route", "tool": "ecc", "state": "Unstart"}],
        }
        engine_flow = EngineFlow(workspace)
        workspace_step = EccStep(name="route", directory=tmp_path, tool="ecc")
        engine_flow.workspace_steps = [workspace_step]
        engine_flow.engine_db = SimpleNamespace(engine=None)

        def raise_on_run(**_kwargs):
            raise RuntimeError("tool crashed")

        monkeypatch.setattr(tools, "run_step", raise_on_run)
        monkeypatch.setattr(engine_flow, "check_step_result", lambda **_kwargs: True)

        state = engine_flow.run_step(workspace_step)
        assert state == StateEnum.Imcomplete

    def test_no_exception_uses_file_check(self, monkeypatch, tmp_path):
        (tmp_path / "home").mkdir(exist_ok=True)
        workspace = Workspace(directory=tmp_path, flow=Flow(path=tmp_path / "home" / "flow.json"))
        engine_flow = EngineFlow(workspace)
        engine_flow.workspace.flow.data = {
            "steps": [{"name": "route", "tool": "ecc", "state": "Unstart"}],
        }
        workspace_step = EccStep(name="route", directory=tmp_path, tool="ecc")
        engine_flow.workspace_steps = [workspace_step]
        engine_flow.engine_db = SimpleNamespace(engine=None)

        monkeypatch.setattr(tools, "run_step", lambda **_kwargs: True)
        monkeypatch.setattr(engine_flow, "check_step_result", lambda **_kwargs: True)
        monkeypatch.setattr(tools, "save_layout_image", lambda **_kwargs: True)
        monkeypatch.setattr(tools, "build_step_metrics", lambda **_kwargs: StepMetrics(data={}))

        state = engine_flow.run_step(workspace_step)
        assert state == StateEnum.Success


class TestCreateStepFailureBreaksChain:
    """Regression: create_step(None) must break the flow chain and mark step Incomplete."""

    def test_none_step_breaks_loop(self, monkeypatch, tmp_path):
        flow_path = tmp_path / "flow.json"
        flow_data = {
            "steps": [
                {"name": "SYNTHESIS", "tool": "yosys", "state": "Unstart"},
                {"name": "FLOORPLAN", "tool": "ecc", "state": "Unstart"},
                {"name": "NETLIST_OPT", "tool": "ecc", "state": "Unstart"},
            ]
        }
        flow_path.write_text(json.dumps(flow_data), encoding="utf-8")
        workspace = Workspace(directory=tmp_path)
        workspace.flow.path = flow_path
        workspace.flow.data = json.loads(json.dumps(flow_data))
        engine_flow = EngineFlow(workspace)

        call_count = [0]

        def fake_create_step(*args, **kwargs):
            call_count[0] += 1
            if kwargs.get("step") == "FLOORPLAN":
                return None  # simulate tool not found
            return EccStep(name=kwargs["step"], directory=tmp_path, tool=kwargs.get("eda", ""))

        import chipcompiler.tools as tools_mod

        monkeypatch.setattr(tools_mod, "create_step", fake_create_step)
        engine_flow.create_step_workspaces()

        # Only SYNTHESIS should be created; FLOORPLAN fails, NETLIST_OPT never attempted
        assert len(engine_flow.workspace_steps) == 1
        assert engine_flow.workspace_steps[0].name == "SYNTHESIS"
        assert call_count[0] == 2  # SYNTHESIS + FLOORPLAN (NETLIST_OPT skipped)

        # FLOORPLAN should be marked Incomplete in flow data
        fp_step = next(s for s in workspace.flow.data["steps"] if s["name"] == "FLOORPLAN")
        assert fp_step["state"] == StateEnum.Imcomplete.value
        # NETLIST_OPT should stay Unstart (never reached)
        no_step = next(s for s in workspace.flow.data["steps"] if s["name"] == "NETLIST_OPT")
        assert no_step["state"] == "Unstart"

    def test_run_steps_returns_false_when_steps_skipped(self, monkeypatch, tmp_path):
        """run_steps must return False when create_step skipped steps."""
        flow_path = tmp_path / "flow.json"
        flow_data = {
            "steps": [
                {"name": "SYNTHESIS", "tool": "yosys", "state": "Unstart"},
                {"name": "FLOORPLAN", "tool": "ecc", "state": "Unstart"},
            ]
        }
        flow_path.write_text(json.dumps(flow_data), encoding="utf-8")
        workspace = Workspace(directory=tmp_path)
        workspace.flow.path = flow_path
        workspace.flow.data = json.loads(json.dumps(flow_data))
        engine_flow = EngineFlow(workspace)

        # Only create SYNTHESIS
        engine_flow.workspace_steps = [EccStep(name="SYNTHESIS", directory=tmp_path, tool="yosys")]

        # run_steps: only 1 of 2 steps created
        monkeypatch.setattr(engine_flow, "run_step", lambda ws, **kw: StateEnum.Success)
        monkeypatch.setattr(
            workspace,
            "logger",
            type(
                "L",
                (),
                {
                    "log_section": lambda self, *a: None,
                    "error": lambda self, *a, **kw: None,
                    "info": lambda self, *a, **kw: None,
                    "warning": lambda self, *a, **kw: None,
                },
            )(),
        )

        result = engine_flow.run_steps()
        assert result is False


class TestEccRunStepReturnType:
    """Regression: ecc/runner.py run_step must return bool, not StateEnum."""

    def test_returns_false_when_not_available(self, monkeypatch):
        from chipcompiler.tools.ecc import runner as ecc_runner

        monkeypatch.setattr(ecc_runner, "is_eda_exist", lambda: False)
        result = ecc_runner.run_step(
            workspace=None,
            step=EccStep(name="FLOORPLAN", directory=None, tool="ecc"),
        )
        assert result is False
        assert isinstance(result, bool)


class TestKlayoutRunStep:
    """Regression: klayout run_step was a no-op pass returning None."""

    def test_returns_false(self):
        pytest.importorskip("klayout")
        from chipcompiler.tools.klayout_tool.runner import run_step

        result = run_step()
        assert result is False


class TestMandatoryArtifactFailure:
    """Tool exits normally but required artifact missing → state must be Incomplete."""

    def test_synthesis_missing_verilog_gives_incomplete(self, monkeypatch, tmp_path):
        from chipcompiler.data import YosysOutput, YosysStep

        workspace = Workspace(directory=tmp_path)
        workspace.flow.path = tmp_path / "flow.json"
        workspace.flow.data = {
            "steps": [{"name": "SYNTHESIS", "tool": "yosys", "state": "Unstart"}]
        }
        engine_flow = EngineFlow(workspace)
        ws_step = YosysStep(
            name="SYNTHESIS",
            directory=tmp_path,
            tool="yosys",
            output=YosysOutput(verilog=tmp_path / "missing.v"),
        )
        engine_flow.workspace_steps = [ws_step]

        monkeypatch.setattr("chipcompiler.tools.run_step", lambda **kw: True)
        monkeypatch.setattr("chipcompiler.tools.save_layout_image", lambda **kw: True)
        monkeypatch.setattr("chipcompiler.tools.build_step_metrics", lambda **kw: None)

        state = engine_flow.run_step(ws_step)
        assert state == StateEnum.Imcomplete

    def test_harden_missing_lef_gives_incomplete(self, monkeypatch, tmp_path):
        workspace = Workspace(directory=tmp_path)
        workspace.flow.path = tmp_path / "flow.json"
        workspace.flow.data = {"steps": [{"name": "HARDEN", "tool": "ecc", "state": "Unstart"}]}
        engine_flow = EngineFlow(workspace)
        ws_step = EccStep(
            name="HARDEN",
            directory=tmp_path,
            tool="ecc",
            output=EccOutput(
                lef=tmp_path / "missing.lef",
                lib=tmp_path / "gcd.lib",
            ),
        )
        (tmp_path / "gcd.lib").write_text("")
        engine_flow.workspace_steps = [ws_step]

        monkeypatch.setattr("chipcompiler.tools.run_step", lambda **kw: True)

        state = engine_flow.run_step(ws_step)
        assert state == StateEnum.Imcomplete

    def test_floorplan_missing_gds_gives_incomplete(self, monkeypatch, tmp_path):
        workspace = Workspace(directory=tmp_path)
        workspace.flow.path = tmp_path / "flow.json"
        workspace.flow.data = {"steps": [{"name": "FLOORPLAN", "tool": "ecc", "state": "Unstart"}]}
        engine_flow = EngineFlow(workspace)
        ws_step = EccStep(
            name="FLOORPLAN",
            directory=tmp_path,
            tool="ecc",
            output=EccOutput(
                def_=tmp_path / "gcd.def",
                verilog=tmp_path / "gcd.v",
            ),
        )
        (tmp_path / "gcd.def").write_text("")
        (tmp_path / "gcd.v").write_text("")
        engine_flow.workspace_steps = [ws_step]

        monkeypatch.setattr("chipcompiler.tools.run_step", lambda **kw: True)

        state = engine_flow.run_step(ws_step)
        assert state == StateEnum.Imcomplete

    def test_exception_with_partial_output_gives_incomplete(self, monkeypatch, tmp_path):
        workspace = Workspace(directory=tmp_path)
        workspace.flow.path = tmp_path / "flow.json"
        workspace.flow.data = {"steps": [{"name": "FLOORPLAN", "tool": "ecc", "state": "Unstart"}]}
        engine_flow = EngineFlow(workspace)
        ws_step = EccStep(
            name="FLOORPLAN",
            directory=tmp_path,
            tool="ecc",
            output=EccOutput(
                def_=tmp_path / "gcd.def",
            ),
        )
        (tmp_path / "gcd.def").write_text("")
        engine_flow.workspace_steps = [ws_step]

        def crash(**kw):
            raise RuntimeError("tool crashed mid-execution")

        monkeypatch.setattr("chipcompiler.tools.run_step", crash)

        state = engine_flow.run_step(ws_step)
        assert state == StateEnum.Imcomplete
