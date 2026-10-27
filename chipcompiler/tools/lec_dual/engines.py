"""Per-engine tool-module loading for the dual LEC composite."""

import importlib
from typing import Any

from chipcompiler.data import LECEngineEnum
from chipcompiler.tools.protocol import ToolModule


def lec_engine_module(engine: LECEngineEnum) -> ToolModule[Any]:
    """The physical tool module for one engine.

    The composite itself has no physical module; spawning is always over
    ``LECEngineEnum.DUAL.spawn_engines``.
    """
    if engine is LECEngineEnum.DUAL:
        raise ValueError("lec_dual is a composite; it has no physical engine module")
    module = importlib.import_module(f"chipcompiler.tools.{engine.value}")
    if not isinstance(module, ToolModule):
        raise ImportError(f"{engine.value} does not implement the tool module contract")
    return module
