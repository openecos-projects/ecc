import json

from chipcompiler.data import EccStep, OriginDesign, StateEnum, StepEnum, Workspace
from chipcompiler.tools.ecc import metrics as ecc_metrics
from chipcompiler.tools.ecc.subflow import EccSubFlow
from chipcompiler.tools.ecc_dreamplace import builder, runner


def test_run_step_dispatches_macro_placement(monkeypatch):
    calls = []
    workspace = Workspace()
    step = EccStep(name=StepEnum.MACRO_PLACEMENT.value)

    monkeypatch.setattr(runner, "is_eda_exist", lambda: True)
    monkeypatch.setattr(
        runner,
        "run_macro_placement",
        lambda **kwargs: calls.append(kwargs) or True,
        raising=False,
    )

    assert runner.run_step(workspace=workspace, step=step) is True
    assert calls == [{"workspace": workspace, "step": step, "ecc_module": None}]


def test_macro_placement_analysis_does_not_report_generic_qor_metrics(tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = builder.build_step(
        workspace=workspace,
        step_name=StepEnum.MACRO_PLACEMENT.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    builder.build_step_space(step)
    assert step.feature.db is not None
    step.feature.db.write_text(
        json.dumps(
            {
                "Design Layout": {"die_area": 100.0, "core_area": 80.0},
                "Design Statis": {"num_instances": 7},
            }
        ),
        encoding="utf-8",
    )
    subflow = EccSubFlow(workspace=workspace, workspace_step=step)

    metrics = ecc_metrics.build_step_metrics(workspace=workspace, step=step, subflow=subflow)

    assert metrics is None
    assert not step.analysis.metrics.is_file()
    assert not step.analysis.qor_summary.is_file()


def test_run_macro_placement_saves_snapshot_without_egr_feature_map(monkeypatch, tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = builder.build_step(
        workspace=workspace,
        step_name=StepEnum.MACRO_PLACEMENT.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    builder.build_step_space(step)

    class FakeEccModule:
        def feature_placement_map(self, **_kwargs):
            raise AssertionError("macro placement must not request an EGR feature map")

    class FakeDreamplaceModule:
        def __init__(self, **_kwargs):
            pass

        def run_macro_placement(self):
            return True

    ecc_module = FakeEccModule()
    save_calls = []
    monkeypatch.setattr(
        runner.ecc_runner,
        "get_eda_instance",
        lambda **_kwargs: ecc_module,
    )
    monkeypatch.setattr(runner, "DreamplaceModule", FakeDreamplaceModule)
    monkeypatch.setattr(
        runner.ecc_runner,
        "save_data",
        lambda **kwargs: save_calls.append(kwargs) or True,
    )
    monkeypatch.setattr(runner, "run_analysis", lambda **_kwargs: None)

    assert runner.run_macro_placement(workspace=workspace, step=step) is True
    assert len(save_calls) == 1
    assert save_calls[0]["workspace"] is workspace
    assert save_calls[0]["step"] is step
    assert save_calls[0]["ecc_module"] is ecc_module
    assert save_calls[0]["feature_step"] is False
    run_state = next(item for item in step.subflow.steps if item["name"] == "run macro placement")
    assert run_state["state"] == StateEnum.Success.value


def test_run_macro_placement_fails_when_snapshot_save_fails(monkeypatch, tmp_path):
    workspace = Workspace(
        directory=tmp_path,
        design=OriginDesign(name="gcd", top_module="gcd"),
    )
    step = builder.build_step(
        workspace=workspace,
        step_name=StepEnum.MACRO_PLACEMENT.value,
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
    )
    builder.build_step_space(step)

    class FakeDreamplaceModule:
        def __init__(self, **_kwargs):
            pass

        def run_macro_placement(self):
            return True

    monkeypatch.setattr(runner.ecc_runner, "get_eda_instance", lambda **_kwargs: object())
    monkeypatch.setattr(runner, "DreamplaceModule", FakeDreamplaceModule)
    monkeypatch.setattr(runner.ecc_runner, "save_data", lambda **_kwargs: False)
    monkeypatch.setattr(
        runner,
        "run_analysis",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("analysis must not run after snapshot save failure")
        ),
    )

    assert runner.run_macro_placement(workspace=workspace, step=step) is False
    save_state = next(item for item in step.subflow.steps if item["name"] == "save data")
    assert save_state["state"] == StateEnum.Imcomplete.value
