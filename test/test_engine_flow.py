import json
from hashlib import sha256
from types import SimpleNamespace

from chipcompiler import tools
from chipcompiler.data import StateEnum, StepMetrics, Workspace, WorkspaceStep
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
    workspace_step = WorkspaceStep(
        name="route",
        directory=tmp_path,
        tool="ecc",
        feature={"step": step_feature},
    )
    engine_flow = EngineFlow(workspace)
    engine_flow.workspace_steps = [workspace_step]
    engine_flow.engine_db = SimpleNamespace(engine=None)
    refreshed = []

    monkeypatch.setattr(tools, "run_step", lambda **_kwargs: True)
    monkeypatch.setattr(engine_flow, "check_step_result", lambda **_kwargs: True)
    monkeypatch.setattr(tools, "save_layout_image", lambda **_kwargs: True)

    def refresh_metrics(*, workspace, step):
        refreshed.append(json.loads(step.feature["step"].read_text(encoding="utf-8")))
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
