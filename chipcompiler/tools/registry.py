"""The single table of tool names, their packages and loader entry points.

The registry owns identity only: which package backs a persisted tool name,
which optional tools build deferred when unselected, and the two per-tool
switches the engine reads (dependency check, DB lifetime). How a step
behaves -- metrics/checklist selection, placement handling, parallelism --
stays with the tool module, the flow policy or the step that needs it.
"""

import importlib
import logging
import sys
from dataclasses import dataclass

from chipcompiler.data.types import ToolName


@dataclass(frozen=True)
class ToolSpec:
    """What the engine needs to know about one tool name."""

    module: str
    #: Build unselected steps without importing the tool package.
    deferred: bool = False
    #: The tool's binary is optional and checked lazily by the tool itself.
    skip_dependency_check: bool = False
    #: Release the DB engine after every step owned by this tool.
    closes_db_after_step: bool = False


TOOLS: dict[ToolName, ToolSpec] = {
    ToolName.YOSYS: ToolSpec("yosys"),
    ToolName.ECC: ToolSpec("ecc"),
    ToolName.DREAMPLACE: ToolSpec("ecc_dreamplace", deferred=True),
    ToolName.SIZER: ToolSpec(
        "ecc_sizer",
        deferred=True,
        skip_dependency_check=True,
        closes_db_after_step=True,
    ),
    ToolName.YOSYS_LEC: ToolSpec("yosys_lec"),
    ToolName.KEPLER_FORMAL: ToolSpec("kepler_formal"),
    ToolName.LEC_DUAL: ToolSpec("lec_dual"),
    ToolName.KLAYOUT: ToolSpec("klayout_tool"),
}

#: Tools that can own a flow step; ``klayout`` renders images only.
FLOW_TOOLS = frozenset(TOOLS) - {ToolName.KLAYOUT}
IMAGE_TOOLS = frozenset({ToolName.KLAYOUT})


def tool_spec(name: object) -> ToolSpec | None:
    """The spec for a persisted/declared tool name, or None if unknown."""
    try:
        return TOOLS[ToolName(name)]
    except ValueError:
        return None


def checks_dependency(name: object, *, requested: bool = True) -> bool:
    """Whether the loader should run a tool's dependency check.

    The loader itself always honors its ``check_dependency`` argument; tools
    whose binary is optional declare that here so call sites can opt out
    without changing the loader's public contract.
    """
    spec = tool_spec(name)
    return requested and not (spec is not None and spec.skip_dependency_check)


def _module_identity(name: object) -> tuple[str, ToolSpec] | None:
    """The importable package for a tool name.

    Unknown names are never imported. The one exception is an already-loaded
    module registered under ``chipcompiler.tools.<name>``: the tool-contract
    tests inject fakes that way.
    """
    spec = tool_spec(name)
    if spec is not None:
        return spec.module, spec
    if f"chipcompiler.tools.{name}" in sys.modules:
        return str(name), ToolSpec(str(name))
    return None


def load_tool(name: object, *, check_dependency: bool = True):
    """Import and validate the tool module for *name*, or None.

    Failure semantics are unchanged from the previous loader: an import
    failure, a contract mismatch and a False ``is_eda_exist()`` all log and
    return None; a dependency check that raises propagates to the caller.
    """
    from chipcompiler.tools.protocol import ToolModule, tool_module_functions

    identity = _module_identity(name)
    if identity is None:
        logging.error("EDA tool '%s': unknown tool name", name)
        return None
    module_name, spec = identity

    try:
        eda_module = importlib.import_module(f"chipcompiler.tools.{module_name}")
    except Exception as e:
        logging.error(f"Error load module {name}: {e}")
        return None

    if not isinstance(eda_module, ToolModule):
        missing = [f for f in tool_module_functions() if not hasattr(eda_module, f)]
        logging.error("EDA tool '%s': module loaded but missing interface: %s", name, missing)
        return None

    if check_dependency and not eda_module.is_eda_exist():
        logging.error(
            "EDA tool '%s': dependency check failed (is_eda_exist returned False)",
            name,
        )
        return None

    return eda_module


def load_builder(name: object):
    """The tool's ``builder`` module; raises ImportError like importlib."""
    identity = _module_identity(name)
    if identity is None:
        raise ImportError(f"unknown tool: {name!r}")
    module_name, _spec = identity
    return importlib.import_module(f"chipcompiler.tools.{module_name}.builder")
