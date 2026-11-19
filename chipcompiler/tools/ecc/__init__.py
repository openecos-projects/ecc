from typing import TYPE_CHECKING

from chipcompiler.data import StepEnum
from chipcompiler.data.step_config_reads import ConfigRead

from .builder import build_step, build_step_config, build_step_space
from .checklist import EccChecklist
from .metrics import build_step_metrics
from .module import ECCToolsModule
from .runner import create_db_engine, run_step
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


#: The workspace configs each ECC-Tools step reads (``ToolModule``).
STEP_CONFIG_READS = {
    StepEnum.PRE_FLOORPLAN: (ConfigRead("db"), ConfigRead("floorplan")),
    StepEnum.POST_FLOORPLAN: (
        ConfigRead("db"),
        ConfigRead("floorplan"),
        ConfigRead("macro_location"),
    ),
    StepEnum.PLACEMENT: (ConfigRead("db"),),
    StepEnum.CTS: (ConfigRead("db"), ConfigRead("cts")),
    StepEnum.ROUTING: (ConfigRead("db"), ConfigRead("routing")),
    StepEnum.DRC: (ConfigRead("db"), ConfigRead("drc")),
    StepEnum.ANTENNA_CHECK: (ConfigRead("db"),),
    StepEnum.LEGALIZATION: (ConfigRead("db"),),
    StepEnum.FILLER: (ConfigRead("db"), ConfigRead("filler")),
    StepEnum.RCX: (ConfigRead("db"), ConfigRead("rcx")),
    StepEnum.STA: (ConfigRead("db"), ConfigRead("rcx"), ConfigRead("sta")),
    StepEnum.EMIR: (ConfigRead("db"), ConfigRead("emir")),
}

__all__ = [
    "STEP_CONFIG_READS",
    "is_eda_exist",
    "build_step",
    "build_step_space",
    "build_step_config",
    "run_step",
    "create_db_engine",
    "ECCToolsModule",
    "ECCToolsPlot",
    "build_step_metrics",
    "EccSubFlow",
    "EccSubFlowEnum",
    "EccChecklist",
]
