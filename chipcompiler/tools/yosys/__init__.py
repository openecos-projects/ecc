from chipcompiler.data import StepEnum
from chipcompiler.data.step_config_reads import ConfigRead

from .builder import build_step, build_step_config, build_step_space
from .checklist import YosysChecklist
from .metrics import build_step_metrics
from .runner import run_step
from .subflow import YosysSubFlow
from .utility import is_eda_exist

#: The workspace configs synthesis reads (``ToolModule``): extra Liberty files.
STEP_CONFIG_READS = {
    StepEnum.SYNTHESIS: (ConfigRead("db", ("INPUT", "lib_path")),),
}

__all__ = [
    "STEP_CONFIG_READS",
    "is_eda_exist",
    "build_step",
    "build_step_space",
    "build_step_config",
    "run_step",
    "build_step_metrics",
    "YosysSubFlow",
    "YosysChecklist",
]
