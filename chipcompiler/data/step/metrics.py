"""Step metrics files."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

###########################################################################
# step definition for chip design flow in json format
# step_definition =
# {
#     "name" : "", # step name
#     "tool" : "", # eda tool name
#     "state" : "", # step state
#     "runtime" : "", # step run time
#     "info" : {} # step additional infomation
# }
###########################################################################


@dataclass
class StepMetrics:
    """
    Dataclass for step metrics
    """

    path: str | Path = ""  # metrics file path
    data: dict[str, Any] = field(default_factory=dict[str, Any])  # metrics data
    report: list[Any] = field(default_factory=list[Any])  # metrics report


###########################################################################
# step metrics definition in json format
# step_metrics =
# {
#     "name" : "", # step name
#     "tool" : "", # eda tool name
# }
###########################################################################


def load_metrics(path: str | Path) -> StepMetrics:
    from chipcompiler.utility import json_read

    metrics = StepMetrics()
    metrics.path = path
    metrics.data = cast("dict[str, Any]", json_read(path))
    return metrics


def save_metrics(metrics: StepMetrics) -> bool:
    from chipcompiler.utility import json_write

    return json_write(file_path=metrics.path, data=metrics.data)
