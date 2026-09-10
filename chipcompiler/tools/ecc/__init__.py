from typing import TYPE_CHECKING

from .builder import build_step, build_step_config, build_step_space
from .checklist import EccChecklist
from .metrics import build_step_metrics
from .module import ECCToolsModule
from .runner import create_db_engine, run_step
from .service import get_step_info
from .subflow import EccSubFlow, EccSubFlowEnum
from .utility import is_eda_exist

# ECCToolsPlot pulls in matplotlib through the utility plot helpers, so it is
# re-exported lazily via PEP 562 instead of at package import time.
_PLOT_EXPORTS = frozenset({"ECCToolsPlot"})

if TYPE_CHECKING:
    from .plot import ECCToolsPlot
else:
    # Hidden from type checkers so unknown attributes still fail statically.
    def __getattr__(name: str):
        if name in _PLOT_EXPORTS:
            from . import plot

            return getattr(plot, name)
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    def __dir__() -> list[str]:
        return sorted(set(globals()) | _PLOT_EXPORTS)


__all__ = [
    "is_eda_exist",
    "build_default_flow",
    "build_step",
    "build_step_space",
    "build_step_config",
    "run_step",
    "create_db_engine",
    "ECCToolsModule",
    "ECCToolsPlot",
    "build_step_metrics",
    "get_step_info",
    "EccSubFlow",
    "EccSubFlowEnum",
    "EccChecklist",
]
