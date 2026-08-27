import ctypes
import json
from hashlib import sha256
from types import SimpleNamespace

import pytest

import chipcompiler.engine.flow as flow_module
from chipcompiler import tools
from chipcompiler.data import (
    ChecklistState,
    EccFeature,
    EccOutput,
    EccStep,
    LogPaths,
    StateEnum,
    StepEnum,
    StepMetrics,
    SubflowState,
    Workspace,
    YosysOutput,
    YosysStep,
)
from chipcompiler.engine.flow import EngineFlow
from chipcompiler.tools.ecc.signoff_checklist import refresh_step_checklist


def test_engine_flow_missing_path_is_not_initialized():
    engine_flow = EngineFlow(Workspace())

    assert engine_flow.has_init() is False


def test_engine_flow_persists_run_facts_before_refreshing_qor_analysis(
    monkeypatch,
    tmp_path,
):
    workspace = Workspace()
    workspace.flow.data = {
        "steps": [{"name": "route", "tool": "ecc", "state": "Unstart"}],
    }
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


def test_check_step_result_synthesis_uses_common_verilog(tmp_path):
    verilog = tmp_path / "gcd.v"
    verilog.write_text("module gcd; endmodule\n")
    step = YosysStep(name=StepEnum.SYNTHESIS.value, output=YosysOutput(verilog=verilog))
    assert EngineFlow(Workspace()).check_step_result(step) is True


def test_engine_flow_refreshes_home_checklist_after_harden_success(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    workspace = Workspace(directory=tmp_path)
    workspace.flow.path = home / "flow.json"
    workspace.flow.data = {
        "steps": [{"name": StepEnum.HARDEN.value, "tool": "ecc", "state": StateEnum.Unstart.value}]
    }
    workspace.flow.path.write_text(json.dumps(workspace.flow.data), encoding="utf-8")
    workspace.home.init(home / "home.json")
    workspace.home.set_checklist(home / "checklist.json")
    lef = tmp_path / "gcd.lef"
    lib = tmp_path / "gcd.lib"
    lef.write_text("")
    lib.write_text("")
    workspace_step = EccStep(
        name=StepEnum.HARDEN.value,
        directory=tmp_path / "Harden_ecc",
        tool="ecc",
        output=EccOutput(lef=lef, lib=lib),
        checklist=ChecklistState(path=tmp_path / "Harden_ecc" / "checklist.json"),
    )
    engine_flow = EngineFlow(workspace)
    engine_flow.workspace_steps = [workspace_step]
    engine_flow.engine_db = SimpleNamespace(engine=None)

    def run_tool_step(**_kwargs):
        refresh_step_checklist(workspace, workspace_step)
        items = {
            item["id"]: item
            for item in json.loads((home / "checklist.json").read_text(encoding="utf-8"))[
                "checklist"
            ]
        }
        assert items["flow.harden.completed"]["state"] == "failed"
        assert "Ongoing" in items["flow.harden.completed"]["summary"]
        return True

    monkeypatch.setattr(tools, "run_step", run_tool_step)
    monkeypatch.setattr(tools, "save_layout_image", lambda **_kwargs: True)
    monkeypatch.setattr(tools, "build_step_metrics", lambda **_kwargs: None)

    assert engine_flow.run_step(workspace_step) == StateEnum.Success
    items = {
        item["id"]: item
        for item in json.loads((home / "checklist.json").read_text(encoding="utf-8"))["checklist"]
    }
    assert items["flow.harden.completed"]["state"] == "pass"
    assert items["flow.harden.completed"]["blocked"] is False


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


def test_create_step_workspaces_can_preserve_existing_configs(monkeypatch, tmp_path):
    import chipcompiler.tools as tools_api
    from chipcompiler.data import OriginDesign

    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    initialize_config_values = []

    def fake_create_step(workspace, step, eda, **kwargs):
        initialize_config_values.append(kwargs["initialize_config"])
        return EccStep(name=step, tool=eda)

    monkeypatch.setattr(tools_api, "create_step", fake_create_step)

    flow = EngineFlow(workspace)
    flow.workspace.flow.data = {"steps": [{"name": "Floorplan", "tool": "ecc"}]}
    flow.create_step_workspaces(initialize_config=False)

    assert initialize_config_values == [False]


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

    def test_native_output_precedes_failure_summary(self, monkeypatch, tmp_path):
        workspace = Workspace()
        workspace.flow.data = {
            "steps": [{"name": "place", "tool": "dreamplace", "state": "Unstart"}],
        }
        log_file = tmp_path / "place.log"
        workspace_step = EccStep(
            name="place",
            directory=tmp_path,
            tool="dreamplace",
            log=LogPaths(file=log_file),
        )
        engine_flow = EngineFlow(workspace)
        engine_flow.workspace_steps = [workspace_step]
        engine_flow.engine_db = SimpleNamespace(engine=None)
        monkeypatch.setattr(workspace.logger, "error", print)
        monkeypatch.setattr(workspace.logger, "exception", print)

        def fail_after_native_output(**_kwargs):
            libc = ctypes.CDLL(None)
            libc.fputs(
                b"[native] setup completed\n",
                ctypes.c_void_p.in_dll(libc, "stdout"),
            )
            raise RuntimeError("placement failed")

        monkeypatch.setattr(tools, "run_step", fail_after_native_output)

        assert engine_flow.run_step(workspace_step) == StateEnum.Imcomplete
        contents = log_file.read_text(encoding="utf-8")
        assert contents.index("[native] setup completed") < contents.index(
            "[STEP] place(dreamplace) failed"
        )

    def test_no_exception_uses_file_check(self, monkeypatch, tmp_path):
        workspace = Workspace()
        workspace.flow.data = {
            "steps": [{"name": "route", "tool": "ecc", "state": "Unstart"}],
        }
        engine_flow = EngineFlow(workspace)
        workspace_step = EccStep(name="route", directory=tmp_path, tool="ecc")
        engine_flow.workspace_steps = [workspace_step]
        engine_flow.engine_db = SimpleNamespace(engine=None)

        monkeypatch.setattr(tools, "run_step", lambda **_kwargs: True)
        monkeypatch.setattr(engine_flow, "check_step_result", lambda **_kwargs: True)
        monkeypatch.setattr(tools, "save_layout_image", lambda **_kwargs: True)
        monkeypatch.setattr(tools, "build_step_metrics", lambda **_kwargs: StepMetrics(data={}))

        state = engine_flow.run_step(workspace_step)
        assert state == StateEnum.Success

    def test_marker_persist_failure_does_not_start_tool(self, monkeypatch, tmp_path):
        workspace = Workspace()
        engine_flow = EngineFlow(workspace)
        workspace.flow.data = {
            "steps": [{"name": "place", "tool": "dreamplace", "state": "Unstart", "info": {}}],
        }
        workspace_step = EccStep(name="place", directory=tmp_path, tool="dreamplace")
        engine_flow.workspace_steps = [workspace_step]

        class Observer:
            runtime_operation = {
                "schema": 1,
                "operation_id": "operation-1",
                "runtime_instance_id": "runtime-1",
            }

        monkeypatch.setattr(engine_flow, "save", lambda: False)
        monkeypatch.setattr(
            tools,
            "run_step",
            lambda **_kwargs: pytest.fail("tool must not start without a durable marker"),
        )

        with pytest.raises(RuntimeError, match="failed to persist runtime operation marker"):
            engine_flow.run_step(workspace_step, observer=Observer())

        assert workspace.flow.data["steps"][0] == {
            "name": "place",
            "tool": "dreamplace",
            "state": "Unstart",
            "info": {},
        }

    def test_terminal_persist_failure_keeps_recoverable_marker(self, monkeypatch, tmp_path):
        workspace = Workspace()
        workspace.flow.path = tmp_path / "flow.json"
        flow_data = {
            "steps": [{"name": "place", "tool": "dreamplace", "state": "Unstart", "info": {}}],
        }
        workspace.flow.path.write_text(json.dumps(flow_data), encoding="utf-8")
        workspace.flow.data = flow_data
        engine_flow = EngineFlow(workspace)
        workspace_step = EccStep(name="place", directory=tmp_path, tool="dreamplace")
        engine_flow.workspace_steps = [workspace_step]
        engine_flow.engine_db = SimpleNamespace(engine=None)

        class Observer:
            runtime_operation = {
                "schema": 1,
                "operation_id": "operation-1",
                "runtime_instance_id": "runtime-1",
            }

        saves = iter([True, False, False])
        monkeypatch.setattr(engine_flow, "save", lambda: next(saves))
        monkeypatch.setattr(tools, "run_step", lambda **_kwargs: True)
        monkeypatch.setattr(engine_flow, "check_step_result", lambda **_kwargs: True)

        with pytest.raises(RuntimeError, match="failed to persist terminal state"):
            engine_flow.run_step(workspace_step, observer=Observer())

        step = workspace.flow.data["steps"][0]
        assert step["state"] == StateEnum.Ongoing.value
        assert step["info"]["runtime_operation"]["operation_id"] == "operation-1"

    def test_result_check_system_exit_still_finalizes_step(self, monkeypatch, tmp_path):
        workspace = Workspace()
        workspace.flow.path = tmp_path / "flow.json"
        workspace.flow.data = {
            "steps": [{"name": "place", "tool": "dreamplace", "state": "Unstart", "info": {}}],
        }
        workspace.flow.path.write_text(json.dumps(workspace.flow.data), encoding="utf-8")
        engine_flow = EngineFlow(workspace)
        workspace_step = EccStep(name="place", directory=tmp_path, tool="dreamplace")
        engine_flow.workspace_steps = [workspace_step]
        engine_flow.engine_db = SimpleNamespace(engine=None)
        completed = []

        class Observer:
            runtime_operation = {
                "schema": 1,
                "operation_id": "operation-1",
                "runtime_instance_id": "runtime-1",
            }

            def on_step_completed(self, _step, state, error=None):
                completed.append((state, error))

        monkeypatch.setattr(tools, "run_step", lambda **_kwargs: True)
        monkeypatch.setattr(
            engine_flow,
            "check_step_result",
            lambda **_kwargs: (_ for _ in ()).throw(SystemExit(0)),
        )

        assert engine_flow.run_step(workspace_step, observer=Observer()) == StateEnum.Imcomplete
        assert completed == [
            (
                StateEnum.Imcomplete,
                "place(dreamplace) exited unexpectedly (code 0).",
            )
        ]
        persisted_step = json.loads(workspace.flow.path.read_text(encoding="utf-8"))["steps"][0]
        assert persisted_step["state"] == StateEnum.Imcomplete.value
        assert persisted_step["info"] == {}

    @pytest.mark.parametrize("exit_code", [0, 1])
    def test_system_exit_is_incomplete_and_preserves_error(self, monkeypatch, tmp_path, exit_code):
        workspace = Workspace()
        workspace.flow.path = tmp_path / "flow.json"
        flow_data = {
            "steps": [{"name": "place", "tool": "dreamplace", "state": "Unstart", "info": {}}],
        }
        workspace.flow.path.write_text(json.dumps(flow_data), encoding="utf-8")
        workspace.flow.data = flow_data
        engine_flow = EngineFlow(workspace)
        subflow_path = tmp_path / "subflow.json"
        workspace_step = EccStep(
            name="place",
            directory=tmp_path,
            tool="dreamplace",
            subflow=SubflowState(
                path=subflow_path,
                steps=[{"name": "run placement", "state": "Ongoing"}],
            ),
        )
        engine_flow.workspace_steps = [workspace_step]
        engine_flow.engine_db = SimpleNamespace(engine=None)
        completed = []

        class Observer:
            runtime_operation = {
                "schema": 1,
                "operation_id": "operation-1",
                "runtime_instance_id": "runtime-1",
            }

            def on_step_started(self, _step):
                marker = workspace.flow.data["steps"][0]["info"]["runtime_operation"]
                assert marker["operation_id"] == "operation-1"
                assert marker["started_at"] > 0

            def on_step_completed(self, _step, state, error=None):
                completed.append((state, error))

        monkeypatch.setattr(
            tools, "run_step", lambda **_kwargs: (_ for _ in ()).throw(SystemExit(exit_code))
        )

        assert engine_flow.run_step(workspace_step, observer=Observer()) == StateEnum.Imcomplete
        assert completed == [
            (
                StateEnum.Imcomplete,
                f"place(dreamplace) exited unexpectedly (code {exit_code}).",
            )
        ]
        assert workspace.flow.data["steps"][0]["info"] == {}
        interrupted_step = json.loads(subflow_path.read_text(encoding="utf-8"))["steps"][0]
        assert interrupted_step["name"] == "run placement"
        assert interrupted_step["state"] == StateEnum.Imcomplete.value
        assert interrupted_step["runtime"] == "0:0:0"
        assert interrupted_step["peak memory (mb)"] >= 0


class TestCreateStepFailureBreaksChain:
    """Regression: create_step(None) must break the flow chain and mark step Incomplete."""

    def test_none_step_breaks_loop(self, monkeypatch, tmp_path):
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

        call_count = [0]

        def fake_create_step(*args, **kwargs):
            call_count[0] += 1
            if kwargs.get("step") == "FLOORPLAN":
                return None  # simulate tool not found
            return EccStep(name=kwargs["step"], directory=tmp_path, tool=kwargs.get("eda", ""))

        import chipcompiler.tools as tools_mod

        monkeypatch.setattr(tools_mod, "create_step", fake_create_step)
        engine_flow.create_step_workspaces()

        # Only SYNTHESIS should be created; FLOORPLAN fails and the chain stops.
        assert len(engine_flow.workspace_steps) == 1
        assert engine_flow.workspace_steps[0].name == "SYNTHESIS"
        assert call_count[0] == 2  # SYNTHESIS + FLOORPLAN

        # FLOORPLAN should be marked Incomplete in flow data
        fp_step = next(s for s in workspace.flow.data["steps"] if s["name"] == "FLOORPLAN")
        assert fp_step["state"] == StateEnum.Imcomplete.value

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
