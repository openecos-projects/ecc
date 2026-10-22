"""The tool registry is the single source of tool names and their modules."""

from pathlib import Path

import chipcompiler.tools as tools_package
from chipcompiler.data import LECEngineEnum, ToolName
from chipcompiler.rtl2gds import build_rtl2gds_flow
from chipcompiler.tools.registry import FLOW_TOOLS, IMAGE_TOOLS, TOOLS


def test_registry_registers_every_tool_name_and_nothing_else():
    assert set(TOOLS) == set(ToolName)


def test_registered_modules_are_the_packages_under_tools():
    root = Path(tools_package.__file__).resolve().parent
    packages = {
        entry.name
        for entry in root.iterdir()
        if entry.is_dir() and (entry / "__init__.py").is_file()
    }

    for name, spec in TOOLS.items():
        assert (root / spec.module / "__init__.py").is_file(), name
    # `utility` is shared helpers, not a tool package.
    assert {spec.module for spec in TOOLS.values()} == packages - {"utility"}


def test_lec_engine_names_are_tool_names():
    # The two enums stay separate types; only their names must agree.
    assert set(LECEngineEnum) <= set(ToolName)


def test_flow_tools_and_image_tools_partition_the_registry():
    assert FLOW_TOOLS.isdisjoint(IMAGE_TOOLS)
    assert set(ToolName) == FLOW_TOOLS | IMAGE_TOOLS

    chain_tools = {str(tool) for _step, tool, _state in build_rtl2gds_flow()}
    assert chain_tools <= {name.value for name in FLOW_TOOLS}
    assert ToolName.KLAYOUT.value not in chain_tools
