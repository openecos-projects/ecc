import json
from hashlib import sha256
from types import SimpleNamespace

import pytest

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


@pytest.mark.parametrize(
    ("tool_outcome", "expected_state"),
    [
        (False, StateEnum.Imcomplete),
        (StateEnum.Invalid, StateEnum.Invalid),
        (RuntimeError("native tool failed"), StateEnum.Imcomplete),
    ],
)
def test_engine_flow_requires_successful_tool_result(
    monkeypatch,
    tmp_path,
    tool_outcome,
    expected_state,
):
    workspace = Workspace(directory=tmp_path, flow=Flow(path=tmp_path / "flow.json"))
    engine_flow = EngineFlow(workspace)
    workspace.flow.data = {
        "steps": [{"name": "route", "tool": "ecc", "state": "Unstart"}],
    }
    workspace_step = EccStep(name="route", directory=tmp_path, tool="ecc")
    engine_flow.workspace_steps = [workspace_step]
    engine_flow.engine_db = SimpleNamespace(engine=None)
    monkeypatch.setattr(engine_flow, "check_step_result", lambda **_kwargs: True)

    def run_step(**_kwargs):
        if isinstance(tool_outcome, Exception):
            raise tool_outcome
        return tool_outcome

    monkeypatch.setattr(tools, "run_step", run_step)

    assert engine_flow.run_step(workspace_step) is expected_state
    assert engine_flow.check_state("route", "ecc", expected_state)


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
