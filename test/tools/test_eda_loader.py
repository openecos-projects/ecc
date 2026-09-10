import sys
from types import ModuleType, SimpleNamespace

from chipcompiler.data import StepMetrics
from chipcompiler.tools import eda


def _install_tool_module(monkeypatch, module_name, *, exists=True, build_metrics=None):
    module = ModuleType(f"chipcompiler.tools.{module_name}")
    module.is_eda_exist = lambda: exists
    module.build_step_space = lambda step: None
    module.build_step_config = lambda workspace, step: None
    module.run_step = lambda workspace, step, ecc_module=None: True
    module.build_step_metrics = build_metrics or (
        lambda workspace, step: StepMetrics(path="metrics.json", data={"tool": step.tool})
    )
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return module


def test_build_step_metrics_dispatches_to_tool_metrics_builder(monkeypatch):
    seen = {}

    def build_metrics(workspace, step):
        seen["workspace"] = workspace
        seen["step"] = step
        return StepMetrics(path="analysis/fake_metrics.json", data={"cell_number": 42})

    _install_tool_module(monkeypatch, "fake_eda", build_metrics=build_metrics)
    workspace = SimpleNamespace(name="workspace")
    step = SimpleNamespace(tool="fake_eda")

    metrics = eda.build_step_metrics(workspace, step)

    assert metrics == StepMetrics(path="analysis/fake_metrics.json", data={"cell_number": 42})
    assert seen == {"workspace": workspace, "step": step}


def test_build_step_metrics_returns_none_when_tool_dependency_missing(monkeypatch):
    _install_tool_module(monkeypatch, "missing_eda", exists=False)

    metrics = eda.build_step_metrics(SimpleNamespace(), SimpleNamespace(tool="missing_eda"))

    assert metrics is None


def test_build_step_metrics_loads_sizer_without_binary_dependency(monkeypatch):
    seen = {}

    def build_metrics(workspace, step):
        seen["workspace"] = workspace
        seen["step"] = step
        return StepMetrics(path="analysis/qor_metrics.json", data={"die_area": 1})

    _install_tool_module(monkeypatch, "ecc_sizer", exists=False, build_metrics=build_metrics)
    workspace = SimpleNamespace(name="workspace")
    step = SimpleNamespace(tool="sizer")

    metrics = eda.build_step_metrics(workspace, step)

    assert metrics == StepMetrics(path="analysis/qor_metrics.json", data={"die_area": 1})
    assert seen == {"workspace": workspace, "step": step}


def test_create_step_defers_unselected_optional_tool_when_module_is_unavailable(
    monkeypatch, tmp_path
):
    def fail_if_imported(*_args, **_kwargs):
        raise AssertionError("unselected optional tools must not be imported")

    monkeypatch.setattr(eda, "load_eda_module", fail_if_imported)
    workspace = SimpleNamespace(directory=tmp_path, design=SimpleNamespace(name="gcd"))

    step = eda.create_step(
        workspace=workspace,
        step="placement",
        eda="dreamplace",
        input_def=tmp_path / "input.def",
        input_verilog=tmp_path / "input.v",
        check_dependency=False,
    )

    assert step is not None
    assert step.tool == "dreamplace"
    assert step.directory == tmp_path / "placement_dreamplace"
    assert step.input.def_ == tmp_path / "input.def"


def test_create_step_does_not_defer_selected_optional_tool_when_module_is_unavailable(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(eda, "load_eda_module", lambda *_args, **_kwargs: None)
    workspace = SimpleNamespace(directory=tmp_path, design=SimpleNamespace(name="gcd"))

    step = eda.create_step(
        workspace=workspace,
        step="placement",
        eda="dreamplace",
        input_def=None,
        input_verilog=None,
        check_dependency=True,
    )

    assert step is None


def test_create_step_defers_unselected_sizer_with_sizer_path_convention(monkeypatch, tmp_path):
    def fail_if_imported(*_args, **_kwargs):
        raise AssertionError("unselected optional tools must not be imported")

    monkeypatch.setattr(eda, "load_eda_module", fail_if_imported)
    workspace = SimpleNamespace(directory=tmp_path, design=SimpleNamespace(name="gcd"))

    step = eda.create_step(
        workspace=workspace,
        step="Timing optimization",
        eda="sizer",
        input_def=None,
        input_verilog=None,
        check_dependency=False,
    )

    assert step is not None
    assert step.directory == tmp_path / "timing_optimization_sizer"
    assert step.output.verilog == (
        tmp_path / "timing_optimization_sizer" / "output" / "gcd_timing_optimization.v.gz"
    )
