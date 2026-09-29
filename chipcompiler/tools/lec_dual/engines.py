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
    return importlib.import_module(f"chipcompiler.tools.{engine.value}")
