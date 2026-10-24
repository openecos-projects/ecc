import sys
from types import ModuleType, SimpleNamespace

import pytest

from chipcompiler.data import StepMetrics
from chipcompiler.tools import eda


def _install_tool_module(monkeypatch, module_name, *, exists=True, build_metrics=None):
    import chipcompiler.tools.registry as registry

    module = ModuleType(f"chipcompiler.tools.{module_name}")
    if module_name not in {spec.module for spec in registry.TOOLS.values()}:
        monkeypatch.setattr(registry, "tool_spec", lambda _name: registry.ToolSpec(module_name))
    module.is_eda_exist = lambda: exists
    module.build_step = lambda **kwargs: None
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

    monkeypatch.setattr(eda, "load_tool", fail_if_imported)
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
    monkeypatch.setattr(eda, "load_tool", lambda *_args, **_kwargs: None)
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

    monkeypatch.setattr(eda, "load_tool", fail_if_imported)
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


def test_load_tool_rejects_unknown_names_without_importing_them(monkeypatch):
    import sys

    assert eda.load_tool("does_not_exist") is None
    assert "chipcompiler.tools.does_not_exist" not in sys.modules


def test_load_tool_returns_none_and_logs_when_the_import_fails(monkeypatch, caplog):
    import chipcompiler.tools.registry as registry

    def failing_import(_module_name):
        raise ModuleNotFoundError("simulated missing package")

    monkeypatch.setattr(registry.importlib, "import_module", failing_import)

    assert eda.load_tool("ecc") is None
    assert "Error load module ecc" in caplog.text


def test_load_tool_returns_none_and_logs_on_a_contract_mismatch(monkeypatch, caplog):
    from types import ModuleType

    import chipcompiler.tools.registry as registry

    module = ModuleType("chipcompiler.tools.fake_incomplete")
    monkeypatch.setattr(registry, "tool_spec", lambda _name: registry.ToolSpec("fake_incomplete"))
    module.is_eda_exist = lambda: True
    module.build_step = lambda **kwargs: None
    module.build_step_config = lambda workspace, step: None
    module.run_step = lambda workspace, step, ecc_module=None: True
    monkeypatch.setitem(sys.modules, module.__name__, module)

    assert eda.load_tool("fake_incomplete", check_dependency=False) is None
    assert "missing interface" in caplog.text


def test_load_tool_returns_none_and_logs_when_the_dependency_is_missing(monkeypatch, caplog):
    _install_tool_module(monkeypatch, "fake_absent", exists=False)

    assert eda.load_tool("fake_absent") is None
    assert "dependency check failed" in caplog.text


def test_load_tool_propagates_a_dependency_runtime_error(monkeypatch):
    import pytest

    module = _install_tool_module(monkeypatch, "fake_raising", exists=True)

    def raise_missing_dependency():
        raise RuntimeError("native dependency is not installed")

    module.is_eda_exist = raise_missing_dependency

    with pytest.raises(RuntimeError, match="native dependency is not installed"):
        eda.load_tool("fake_raising")


@pytest.mark.parametrize(
    "tool,probe",
    [
        ("yosys", ("chipcompiler.tools.yosys.utility", "get_yosys_command", lambda: None)),
        (
            "kepler_formal",
            (
                "chipcompiler.tools.kepler_formal.utility",
                "get_kepler_formal_command",
                lambda: None,
            ),
        ),
        (
            "lec_dual",
            (
                "chipcompiler.tools.lec_dual.utility",
                "engine_availability",
                lambda engine: (False, f"{engine} missing"),
            ),
        ),
    ],
)
def test_load_tool_propagates_a_real_missing_dependency(monkeypatch, tool, probe):
    import importlib

    module_path, attribute, replacement = probe
    monkeypatch.setattr(importlib.import_module(module_path), attribute, replacement)

    with pytest.raises(RuntimeError):
        eda.load_tool(tool)


@pytest.mark.parametrize("tool", ["yosys", "kepler_formal", "lec_dual"])
def test_load_tool_propagates_the_production_dependency_error(monkeypatch, tool):
    import importlib

    module = importlib.import_module(f"chipcompiler.tools.{tool}")

    def raise_missing_dependency():
        raise RuntimeError(f"{tool} dependency is not installed")

    monkeypatch.setattr(module, "is_eda_exist", raise_missing_dependency)

    with pytest.raises(RuntimeError, match=f"{tool} dependency"):
        eda.load_tool(tool)


def test_load_tool_does_not_attempt_an_unknown_import(monkeypatch):
    import chipcompiler.tools.registry as registry

    imported = []
    monkeypatch.setattr(
        registry.importlib,
        "import_module",
        lambda module_name: imported.append(module_name) or None,
    )

    assert eda.load_tool("does_not_exist") is None
    assert imported == []


def test_load_tool_checks_sizer_dependency_when_the_caller_asks(monkeypatch):
    module = _install_tool_module(monkeypatch, "ecc_sizer", exists=False)
    calls = []
    module.is_eda_exist = lambda: calls.append(True) or False

    assert eda.load_tool("sizer", check_dependency=True) is None
    assert calls == [True]
    assert eda.load_tool("sizer", check_dependency=False) is module


def test_load_builder_raises_import_error_for_unknown_and_missing_modules(monkeypatch):
    import pytest

    from chipcompiler.tools.registry import load_builder

    _install_tool_module(monkeypatch, "fake_conforming", exists=True)

    with pytest.raises(ImportError):
        load_builder("does_not_exist")
    with pytest.raises(ImportError):
        load_builder("fake_conforming")
