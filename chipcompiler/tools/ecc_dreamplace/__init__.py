from chipcompiler.data import SkippableStepEnum, StepEnum
from chipcompiler.data.step_config_reads import ConfigRead

from .builder import build_step, build_step_config, build_step_space
from .metrics import build_step_metrics
from .runner import legalize_layout, run_step
from .utility import is_eda_exist

#: The workspace configs each DreamPlace step reads (``ToolModule``). A timing
#: step hands the whole STA config to DreamPlace's native timer.
STEP_CONFIG_READS = {
    StepEnum.MACRO_PLACEMENT: (ConfigRead("dreamplace"), ConfigRead("macro_location")),
    StepEnum.PLACEMENT: (ConfigRead("dreamplace"), ConfigRead("sta")),
    SkippableStepEnum.DIFF_OPT: (ConfigRead("dreamplace"), ConfigRead("sta")),
    StepEnum.DIFF_SIZING: (ConfigRead("dreamplace"), ConfigRead("sta")),
    StepEnum.LEGALIZATION: (ConfigRead("dreamplace"),),
}

__all__ = [
    "STEP_CONFIG_READS",
    "build_step",
    "build_step_config",
    "build_step_metrics",
    "build_step_space",
    "is_eda_exist",
    "legalize_layout",
    "run_step",
]
