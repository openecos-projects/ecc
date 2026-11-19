from chipcompiler.data import SkippableStepEnum, StepEnum
from chipcompiler.data.step_config_reads import ConfigRead

from .builder import (
    build_step,
    build_step_config,
    build_step_space,
    sizer_staging_def,
    sizer_staging_verilog,
)
from .metrics import build_step_metrics
from .runner import run_step
from .utility import (
    find_sizer_root,
    get_sizer_command,
    get_sizer_root,
    is_eda_exist,
    is_sizer_runtime_exist,
)

#: The workspace configs each Sizer step reads (``ToolModule``): the MIN
#: corner Liberty files, the routing layer bounds and the hold-stage settings.
_SIZER_READS = (
    ConfigRead("db"),
    ConfigRead("sizer"),
    ConfigRead("sta", ("liberty",)),
    ConfigRead("routing", ("RT", "-bottom_routing_layer")),
    ConfigRead("routing", ("RT", "-top_routing_layer")),
)
STEP_CONFIG_READS = {
    StepEnum.PREPLACE: _SIZER_READS,
    SkippableStepEnum.TIMING_OPT: (*_SIZER_READS, ConfigRead("dreamplace")),
}

__all__ = [
    "STEP_CONFIG_READS",
    "build_step",
    "build_step_config",
    "build_step_metrics",
    "build_step_space",
    "find_sizer_root",
    "get_sizer_command",
    "get_sizer_root",
    "is_eda_exist",
    "is_sizer_runtime_exist",
    "run_step",
    "sizer_staging_def",
    "sizer_staging_verilog",
]
