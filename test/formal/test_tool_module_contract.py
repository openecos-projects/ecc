"""Tool-module contract conformance for every flow-step tool package.

Discovery-based: packages under ``chipcompiler/tools/`` are imported and
checked against :class:`chipcompiler.tools.protocol.ToolModule` — presence
via ``isinstance``, plus the contract functions' parameter names and
``run_step``'s ``bool`` return annotation. CI runs no pyright, so the
signature surface is asserted here. A newly added tool package that does
not satisfy the contract fails this test; there is no pass list to forget.

Exemptions (neither is a flow-step tool; exempting anything else requires
editing this list, and the discovery assertion names it):
"""

import importlib
import inspect
import sys
from pathlib import Path
from types import ModuleType

import pytest

from chipcompiler.tools import eda
from chipcompiler.tools.protocol import ToolModule, tool_module_functions

_EXEMPT_PACKAGES = {
    # Image-only utility behind save_gds_image; also not importable without
    # the optional klayout native package.
    "klayout_tool",
    # Shared helper package; owns no step type.
    "utility",
}


def _discovered_tool_packages() -> list[str]:
    tools_dir = Path(eda.__file__).resolve().parent
    return sorted(
        entry.name
        for entry in tools_dir.iterdir()
        if entry.is_dir()
        and (entry / "__init__.py").is_file()
        and entry.name not in _EXEMPT_PACKAGES
    )


def _assert_contract_signature(module: ModuleType, function_name: str) -> None:
    contract = tool_module_functions()[function_name]
    function = getattr(module, function_name)
    parameters = list(inspect.signature(function).parameters.values())
    expected_names = list(contract.parameters)
    actual_names = [parameter.name for parameter in parameters[: len(expected_names)]]
    assert actual_names == expected_names, (
        f"{module.__name__}.{function_name} parameter prefix {actual_names} "
        f"!= contract {expected_names}"
    )
    extra = parameters[len(expected_names) :]
    undeclared_required = [
        parameter.name for parameter in extra if parameter.default is inspect.Parameter.empty
    ]
    assert not undeclared_required, (
        f"{module.__name__}.{function_name} adds required parameters "
        f"beyond the contract: {undeclared_required}"
    )


def _assert_contract_conformance(module: ModuleType) -> None:
    assert isinstance(module, ToolModule)
    for function_name in tool_module_functions():
        _assert_contract_signature(module, function_name)
    assert inspect.signature(module.run_step).return_annotation is bool, (
        f"{module.__name__}.run_step must annotate -> bool, got "
        f"{inspect.signature(module.run_step).return_annotation!r}"
    )


@pytest.mark.parametrize("package", _discovered_tool_packages())
def test_tool_module_contract(package):
    module = importlib.import_module(f"chipcompiler.tools.{package}")
    _assert_contract_conformance(module)


def test_discovery_finds_flow_step_tools():
    discovered = _discovered_tool_packages()
    assert {
        "ecc",
        "ecc_dreamplace",
        "ecc_sizer",
        "yosys",
        "yosys_lec",
        "kepler_formal",
    } <= set(discovered), (
        f"discovery regressed; packages exempt only via {_EXEMPT_PACKAGES}: {discovered}"
    )


def _conforming_fake_module() -> ModuleType:
    def build_step(
        workspace,
        step_name,
        input_def,
        input_verilog,
        input_db=None,
        output_def=None,
        output_verilog=None,
        output_gds=None,
    ):
        return None

    module = ModuleType("chipcompiler.tools.fake_conforming")
    module.is_eda_exist = lambda: True
    module.build_step = build_step
    module.build_step_space = lambda step: None
    module.build_step_config = lambda workspace, step: None
    module.run_step = lambda workspace, step, ecc_module=None: True
    # Lambdas carry no return annotation; annotate the contract-critical one.
    module.run_step.__annotations__["return"] = bool
    return module


def test_fake_conforming_module_passes():
    _assert_contract_conformance(_conforming_fake_module())


def test_module_missing_run_step_fails_contract():
    module = _conforming_fake_module()
    del module.run_step
    assert not isinstance(module, ToolModule)


def test_module_with_non_bool_run_step_fails_contract():
    module = _conforming_fake_module()
    module.run_step.__annotations__["return"] = int
    with pytest.raises(AssertionError, match="run_step must annotate"):
        _assert_contract_conformance(module)


def test_module_with_wrong_parameter_names_fails_contract():
    module = _conforming_fake_module()
    module.build_step_config = lambda ws, step: None
    with pytest.raises(AssertionError, match="parameter prefix"):
        _assert_contract_conformance(module)


def test_load_eda_module_rejects_module_missing_contract_member(monkeypatch):
    module = _conforming_fake_module()
    del module.build_step_space
    monkeypatch.setitem(sys.modules, module.__name__, module)

    assert eda.load_eda_module("fake_conforming", check_dependency=False) is None


def test_load_eda_module_accepts_conforming_module(monkeypatch):
    module = _conforming_fake_module()
    monkeypatch.setitem(sys.modules, module.__name__, module)

    assert eda.load_eda_module("fake_conforming", check_dependency=False) is module
